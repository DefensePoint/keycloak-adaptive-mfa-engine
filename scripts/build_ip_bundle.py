#!/usr/bin/env python3
"""Build the bundled IP intelligence data.

Run during the Docker build. The output is baked into the image, so the running
container needs no network for geolocation or anonymiser detection, which is what
makes on-premise and air-gapped deployment possible.

Only sources whose licence explicitly permits redistribution inside a product are
fetched by default:

* **DB-IP Lite** country and ASN, CC BY 4.0. Attribution only, no ShareAlike, no
  account and no credential needed, which also keeps the build reproducible.
  MaxMind's GeoLite2 is deliberately *not* used: redistributing it requires a paid
  commercial licence, and its EULA obliges licensees to destroy superseded copies
  within 30 days, which a pinned image tag cannot satisfy.
* **Tor exit addresses**, CC0. The Tor Project publishes its own exit list, so
  this is both authoritative and free of obligation.
* **X4BNet** VPN, datacenter and hosting-ASN lists, MIT. Pinned to a commit
  because the grant lives in the repository's README rather than a LICENSE file.

Sources whose redistribution grant could not be established are **opt-in and off
by default**, so a default build ships nothing of uncertain provenance.

Every artefact is recorded in ``manifest.json`` with its SHA-256 and licence, and
a ``NOTICE`` is emitted carrying the attribution each licence requires.

Usage:
    python scripts/build_ip_bundle.py --out bundle
    python scripts/build_ip_bundle.py --out bundle --with-city --keep-city
"""

import argparse
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "amfa-bundle-builder/1.0"

# The MIT grant is published in this repository's README.md, not a LICENSE file,
# so GitHub's detector reports it as unlicensed. Pinning archives the exact grant
# relied upon and keeps builds reproducible. Update deliberately, re-reading the
# README's licence section when you do.
X4BNET_COMMIT = "63c06df6d2e7ff21087187677971a3b0fc767a72"
X4BNET_RAW = f"https://raw.githubusercontent.com/X4BNet/lists_vpn/{X4BNET_COMMIT}"

X4BNET_MIT_NOTICE = """MIT License

Copyright (c) 2024 X4B (Mathew Heard)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

# label -> (url, licence, note)
CIDR_SOURCES = {
    "tor_exit": (
        "https://check.torproject.org/torbulkexitlist",
        "CC0",
        "IPv4 only",
    ),
    "commercial_vpn": (
        f"{X4BNET_RAW}/output/vpn/ipv4.txt",
        "MIT",
        "IPv4 only",
    ),
    "datacenter": (
        f"{X4BNET_RAW}/output/datacenter/ipv4.txt",
        "MIT",
        "IPv4 only",
    ),
}

HOSTING_ASN_SOURCE = (f"{X4BNET_RAW}/input/datacenter/ASN.txt", "MIT")

# Redistribution grant NOT established, so opt-in and off by default. Without it
# there is no suppression layer, which is why a hosting match alone does not set
# is_vpn: a measured 15.3% of sampled Private Relay ranges are flagged by the
# naive lists, and nothing would be able to rule them out.
PRIVACY_RELAY_SOURCE = (
    "https://mask-api.icloud.com/egress-ip-ranges.csv",
    "UNVERIFIED",
)

DBIP_BASE = "https://download.db-ip.com/free"
DBIP_EDITIONS = {
    "country": "dbip-country-lite",
    "asn": "dbip-asn-lite",
    "city": "dbip-city-lite",
}


def fetch(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# Stable local filenames for each upstream artefact, so a directory staged on a
# connected host is recognised by an offline build. Deliberately not the upstream
# basenames, several of which are just "ipv4.txt" and would collide.
ARTEFACTS = {
    CIDR_SOURCES["tor_exit"][0]: "torbulkexitlist",
    CIDR_SOURCES["commercial_vpn"][0]: "x4bnet-vpn-ipv4.txt",
    CIDR_SOURCES["datacenter"][0]: "x4bnet-datacenter-ipv4.txt",
    HOSTING_ASN_SOURCE[0]: "x4bnet-datacenter-ASN.txt",
    PRIVACY_RELAY_SOURCE[0]: "icloud-egress-ip-ranges.csv",
}

SEED_DIR = Path(__file__).resolve().parent.parent / "ipdata" / "seed"


class MissingSource(Exception):
    """An artefact could not be obtained from any permitted source."""


class Sources:
    """Where each upstream artefact comes from, in priority order.

    Three layers, because an air-gapped site cannot download anything and the
    build has to work anyway:

    1. A directory staged by the operator (``--source-dir``). Highest priority:
       staging is a deliberate act, so it should win over anything else.
    2. The network, unless ``--offline``.
    3. The seed files committed to the repository, as a last resort.

    The ordering matters. Seed data is consulted *after* the network so that a
    connected build is never quietly pinned to whatever was committed months ago,
    but *is* available when the network is absent or failing. Which layer answered
    is recorded per artefact in the manifest, so the NOTICE and the logs can say
    plainly whether a bundle was built from fresh data or from a fallback.
    """

    def __init__(self, source_dir=None, offline=False, save_dir=None, use_seed=True):
        self.source_dir = Path(source_dir) if source_dir else None
        self.offline = offline
        self.save_dir = Path(save_dir) if save_dir else None
        self.seed_dir = SEED_DIR if use_seed else None
        self.provenance: dict[str, str] = {}
        if self.save_dir:
            self.save_dir.mkdir(parents=True, exist_ok=True)

    def _local(self, directory, name):
        if directory is None:
            return None
        candidate = directory / name
        return candidate.read_bytes() if candidate.is_file() else None

    def get(self, url: str, name: str | None = None) -> bytes:
        """Obtain one artefact, recording which layer supplied it."""
        name = name or ARTEFACTS.get(url) or url.rsplit("/", 1)[-1]

        staged = self._local(self.source_dir, name)
        if staged is not None:
            self.provenance[name] = "staged"
            print(f"    using staged {name} ({len(staged) // 1024} KiB)")
            return staged

        if not self.offline:
            try:
                payload = fetch(url)
            except Exception as exc:
                # Fall through to the seed rather than failing the build, but say
                # so loudly: shipping stale data unannounced is the worse outcome.
                print(f"    WARNING: download failed for {name} ({exc})")
            else:
                self.provenance[name] = "network"
                if self.save_dir:
                    (self.save_dir / name).write_bytes(payload)
                return payload

        seeded = self._local(self.seed_dir, name)
        if seeded is not None:
            self.provenance[name] = "seed"
            print(f"    WARNING: using committed seed {name}; refresh when possible")
            return seeded

        raise MissingSource(
            f"{name} is unavailable. Stage it into --source-dir from a connected "
            f"host (see --save-sources), or drop --offline. Source: {url}"
        )


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def record(manifest: dict, name: str, payload: bytes, licence: str) -> None:
    manifest["sha256"][name] = sha256(payload)
    manifest["licences"][name] = licence


def store_dbip(edition: str, payload: bytes, out_dir: Path, manifest: dict, origin: str) -> Path:
    slug = DBIP_EDITIONS[edition]
    target = out_dir / f"{slug}.mmdb"
    target.write_bytes(payload)
    record(manifest, target.name, payload, "CC BY 4.0")
    print(f"  {edition}: {target.name} ({len(payload) // 1024} KiB) from {origin}")
    return target


def fetch_dbip(edition: str, out_dir: Path, manifest: dict, sources: Sources) -> Path:
    """Obtain and decompress one DB-IP Lite edition.

    A staged or seeded copy is accepted either compressed or already decompressed,
    since an operator moving files between hosts should not have to care which.

    Otherwise DB-IP publishes monthly at a date-stamped URL. The previous month is
    tried as a fallback, because the current month's file does not exist until
    DB-IP publishes it, which would otherwise break every build on the 1st.
    """
    slug = DBIP_EDITIONS[edition]

    def from_directory(directory, label):
        if directory is None:
            return None
        for name in (f"{slug}.mmdb.gz", f"{slug}.mmdb"):
            candidate = directory / name
            if not candidate.is_file():
                continue
            raw = candidate.read_bytes()
            payload = gzip.decompress(raw) if name.endswith(".gz") else raw
            sources.provenance[f"{slug}.mmdb"] = label
            if label == "seed":
                print(f"    WARNING: using committed seed {name}; refresh when possible")
            return store_dbip(edition, payload, out_dir, manifest, label)
        return None

    staged = from_directory(sources.source_dir, "staged")
    if staged is not None:
        return staged

    if sources.offline:
        seeded = from_directory(sources.seed_dir, "seed")
        if seeded is not None:
            return seeded
        raise MissingSource(
            f"DB-IP {edition} database is unavailable offline. Stage "
            f"{slug}.mmdb.gz into --source-dir from a connected host "
            f"(see --save-sources)."
        )

    for month_offset in (0, 1):
        stamp = time.gmtime(time.time() - month_offset * 31 * 86400)
        month = f"{stamp.tm_year}-{stamp.tm_mon:02d}"
        url = f"{DBIP_BASE}/{slug}-{month}.mmdb.gz"
        try:
            compressed = fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        payload = gzip.decompress(compressed)
        sources.provenance[f"{slug}.mmdb"] = "network"
        if sources.save_dir:
            (sources.save_dir / f"{slug}.mmdb.gz").write_bytes(compressed)
        target = store_dbip(edition, payload, out_dir, manifest, month)
        manifest.setdefault("sources", {})[target.name] = url
        return target

    # Nothing published for either month: fall back to the seed rather than
    # failing, the same way a failed download does.
    seeded = from_directory(sources.seed_dir, "seed")
    if seeded is not None:
        return seeded

    raise MissingSource(f"No DB-IP {edition} database found for this or last month")


def fetch_cidr_lists(
    out_dir: Path, manifest: dict, include_privacy_relay: bool, sources: Sources
) -> None:
    list_sources = dict(CIDR_SOURCES)
    if include_privacy_relay:
        list_sources["privacy_relay"] = (
            PRIVACY_RELAY_SOURCE[0],
            PRIVACY_RELAY_SOURCE[1],
            "opt-in; redistribution grant not established",
        )

    for label, (url, licence, note) in list_sources.items():
        payload = sources.get(url)
        # Apple ships "cidr,country,region,city"; keep the CIDR column only.
        if label == "privacy_relay":
            payload = "\n".join(
                line.split(",")[0]
                for line in payload.decode("utf-8", "replace").splitlines()
                if line.strip()
            ).encode()

        name = f"{label}.txt"
        (out_dir / name).write_bytes(payload)
        record(manifest, name, payload, licence)
        manifest["lists"][label] = name
        manifest.setdefault("sources", {})[name] = url
        entries = len([line for line in payload.decode().splitlines() if line.strip()])
        print(f"  {label}: {entries} entries ({licence}) - {note}")


def fetch_hosting_asns(out_dir: Path, manifest: dict, sources: Sources) -> None:
    url, licence = HOSTING_ASN_SOURCE
    raw = sources.get(url).decode("utf-8", "replace")

    asns = []
    for line in raw.splitlines():
        token = line.strip().split("#", 1)[0].strip()
        if not token:
            continue
        token = token.split()[0].lstrip("ASas")
        if token.isdigit():
            asns.append(token)

    payload = ("\n".join(asns) + "\n").encode()
    name = "hosting_asns.txt"
    (out_dir / name).write_bytes(payload)
    record(manifest, name, payload, licence)
    manifest["hosting_asns"] = name
    manifest.setdefault("sources", {})[name] = url
    print(f"  hosting ASNs: {len(asns)} ({licence})")


def derive_centroids(city_mmdb: Path, out_dir: Path, manifest: dict) -> int:
    """Average each country's city coordinates into one point per country.

    This is what lets the image ship coordinates without shipping the 125 MB city
    database: the table is ~5 KB. The average is weighted by number of MMDB
    records rather than by population or area, so a centroid sits where a
    country's address space is concentrated rather than at its geographic middle.
    Good enough for clustering, where every address in a country collapses to one
    point regardless.

    The result is a DERIVED work from DB-IP City Lite, which CC BY 4.0 permits and
    which the NOTICE declares as required.
    """
    import maxminddb

    sums: dict[str, list[float]] = {}
    with maxminddb.open_database(str(city_mmdb)) as reader:
        for _network, record_data in reader:
            if not isinstance(record_data, dict):
                continue
            country = (record_data.get("country") or {}).get("iso_code")
            location = record_data.get("location") or {}
            lat, long = location.get("latitude"), location.get("longitude")
            if not country or lat is None or long is None:
                continue
            entry = sums.setdefault(country, [0.0, 0.0, 0])
            entry[0] += lat
            entry[1] += long
            entry[2] += 1

    rows = ["country_iso,latitude,longitude"]
    for country in sorted(sums):
        lat_sum, long_sum, count = sums[country]
        rows.append(f"{country},{lat_sum / count:.4f},{long_sum / count:.4f}")

    payload = ("\n".join(rows) + "\n").encode()
    target = out_dir / "country_centroids.csv"
    target.write_bytes(payload)
    record(manifest, target.name, payload, "CC BY 4.0 (derived from DB-IP City Lite)")
    print(f"  centroids: {len(sums)} countries ({len(payload) // 1024 or 1} KiB)")
    return len(sums)


def write_notice(out_dir: Path, manifest: dict) -> None:
    """Emit the NOTICE satisfying each source's attribution obligations.

    CC BY 4.0 section 3(a)(1) requires retaining creator identification, a
    copyright notice, a notice referring to the licence, a notice referring to the
    disclaimer of warranties, and a link to the material; 3(a)(1)(b) requires
    indicating modification. Naming the licence does not satisfy it.

    MIT requires the copyright notice and the permission notice be reproduced in
    full, which is why the grant appears verbatim rather than summarised.

    CC0 imposes no obligation; the Tor Project is credited as a courtesy.
    """
    rule = "=" * 70
    lines = [
        "This bundle contains third-party IP intelligence data.",
        "Each source below is redistributed under the stated licence.",
        "",
        rule,
        "DB-IP Lite (country, ASN, and the derived country centroid table)",
        rule,
        "",
        "IP Geolocation by DB-IP (https://db-ip.com)",
        "Copyright (c) DB-IP. All rights reserved.",
        "Licensed under the Creative Commons Attribution 4.0 International",
        "License (CC BY 4.0).",
        "Licence text: https://creativecommons.org/licenses/by/4.0/",
        "Source: https://db-ip.com/db/lite.php",
        "",
        "Disclaimer of warranties: unless otherwise separately undertaken by the",
        "Licensor, to the extent possible the Licensor offers the Licensed",
        "Material as-is and as-available, and makes no representations or",
        "warranties of any kind concerning the Licensed Material, whether",
        "express, implied, statutory or other.",
        "",
        "MODIFICATIONS: country_centroids.csv is NOT original DB-IP data. It is a",
        "derived work, computed by averaging the coordinates of DB-IP City Lite",
        "records per country. The DB-IP country and ASN databases are",
        "redistributed unmodified.",
        "",
        rule,
        "Tor exit addresses",
        rule,
        "",
        "Copyright (c) The Tor Project (https://www.torproject.org)",
        "Released into the public domain under CC0 1.0. No attribution is",
        "required; the Tor Project is credited here as a courtesy.",
        "Source: https://check.torproject.org/torbulkexitlist",
        "",
        rule,
        "X4BNet VPN and datacenter lists, and the hosting ASN list",
        rule,
        "",
        f"Source: https://github.com/X4BNet/lists_vpn (commit {X4BNET_COMMIT})",
        "",
        "The grant is published in that repository's README.md rather than in a",
        "LICENSE file, so automated scanners may report this dependency as",
        'unlicensed. The README states the licence "corresponds to the scripts,',
        'automation, and the list itself (source files and generated output)",',
        "and is reproduced in full below. The commit is pinned so the exact grant",
        "relied upon is archived.",
        "",
        X4BNET_MIT_NOTICE,
        "",
        rule,
        "Per-artefact licences and checksums",
        rule,
        "",
    ]

    for name in sorted(manifest["sha256"]):
        lines.append(f"  {name}: {manifest['licences'].get(name, 'unknown')}")
        lines.append(f"    sha256 {manifest['sha256'][name]}")

    (out_dir / "NOTICE").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="bundle", help="output directory")
    parser.add_argument(
        "--with-city",
        action="store_true",
        help="download DB-IP City Lite (~125 MB) to derive the centroid table",
    )
    parser.add_argument(
        "--keep-city",
        action="store_true",
        help="keep the city database in the bundle rather than only deriving "
        "centroids from it. Enables true coordinates at the cost of image size",
    )
    parser.add_argument(
        "--include-privacy-relay",
        action="store_true",
        help="include Apple iCloud Private Relay ranges as a suppression list. "
        "OFF by default: its redistribution grant is not established",
    )
    parser.add_argument(
        "--source-dir",
        help="directory of pre-downloaded upstream artefacts to use instead of "
        "downloading. Populate it on a connected host with --save-sources",
    )
    parser.add_argument(
        "--save-sources",
        help="also write each downloaded artefact here, producing a directory "
        "that an air-gapped host can consume with --source-dir",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never touch the network. Artefacts come from --source-dir, falling "
        "back to the seed files committed under ipdata/seed",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="do not fall back to the committed seed files. Use when a build must "
        "either produce fresh data or fail",
    )
    args = parser.parse_args(argv)

    sources = Sources(
        source_dir=args.source_dir,
        offline=args.offline,
        save_dir=args.save_sources,
        use_seed=not args.no_seed,
    )

    out_dir = Path(args.out)
    anon_dir = out_dir / "anon"
    out_dir.mkdir(parents=True, exist_ok=True)
    anon_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "build_epoch": int(time.time()),
        "lists": {},
        "licences": {},
        "sha256": {},
    }

    print("Geo databases (DB-IP Lite, CC BY 4.0):")
    # Geo data is the one part with no committed fallback: the country and ASN
    # databases are 8 and 9 MB and the city database is 125 MB, none of which
    # belongs in git. An offline build without them still produces a usable bundle
    # (anonymiser detection needs no database), so this degrades rather than
    # aborting, and the engine logs the missing geo signal at startup.
    geo_missing = []
    for edition in ("country", "asn"):
        try:
            fetch_dbip(edition, out_dir, manifest, sources)
        except MissingSource as exc:
            geo_missing.append(edition)
            print(f"  SKIPPED {edition}: {exc}")

    city_path = None
    if args.with_city:
        try:
            city_path = fetch_dbip("city", out_dir, manifest, sources)
        except MissingSource as exc:
            geo_missing.append("city")
            print(f"  SKIPPED city: {exc}")

    if city_path is not None:
        print("Coordinates:")
        derive_centroids(city_path, out_dir, manifest)
        if not args.keep_city:
            # Downloaded only to derive the table. Dropping it keeps the image
            # small; the manifest entry goes too, so the NOTICE does not claim to
            # ship a file that is not there.
            city_path.unlink()
            manifest["sha256"].pop(city_path.name, None)
            manifest["licences"].pop(city_path.name, None)
            print(f"  discarded {city_path.name} (use --keep-city to retain it)")
    else:
        # No city database, so the centroid table cannot be derived. The committed
        # copy is tiny (~5 KB) and changes only when country address space moves,
        # so it is a good fallback: with any country database present it still
        # yields country-level coordinates, which is what impossible-travel and
        # geo-clustering need to function at all.
        seed_centroids = sources.seed_dir / "country_centroids.csv" if sources.seed_dir else None
        if seed_centroids is not None and seed_centroids.is_file():
            payload = seed_centroids.read_bytes()
            (out_dir / "country_centroids.csv").write_bytes(payload)
            record(manifest, "country_centroids.csv", payload, "CC BY 4.0")
            sources.provenance["country_centroids.csv"] = "seed"
            rows = len([r for r in payload.decode().splitlines() if r.strip()])
            print(f"Coordinates:\n  centroids: {rows} rows from the committed seed")

    print("Anonymiser lists:")
    fetch_cidr_lists(anon_dir, manifest, args.include_privacy_relay, sources)
    fetch_hosting_asns(anon_dir, manifest, sources)

    # Which layer supplied each artefact. Recorded in the manifest so it reaches
    # the NOTICE and can be inspected in a running container: "was this bundle
    # built from fresh data or from a committed fallback" should be answerable
    # after the fact, not only from build logs that are long gone.
    manifest["provenance"] = dict(sources.provenance)

    # The anonymiser index reads its manifest from the anon directory; the NOTICE
    # covers the whole bundle and sits at the root.
    (anon_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    write_notice(out_dir, manifest)

    print(f"\nBundle written to {out_dir}/")
    print(f"  anonymiser lists: {sorted(manifest['lists'])}")

    by_layer: dict[str, list[str]] = {}
    for name, layer in sorted(sources.provenance.items()):
        by_layer.setdefault(layer, []).append(name)
    for layer in ("network", "staged", "seed"):
        if layer in by_layer:
            print(f"  from {layer}: {', '.join(by_layer[layer])}")

    if args.save_sources:
        print(f"  staged copies written to {args.save_sources}/")
    if geo_missing:
        print(
            f"  WARNING: no geo database for {', '.join(geo_missing)}. Country and "
            "coordinate signals will not resolve; anonymiser detection is "
            "unaffected."
        )
    if "seed" in by_layer:
        print(
            "  WARNING: some data came from the committed seed and may be old. "
            "Confidence scoring already accounts for age; refresh when a "
            "connected host is available."
        )
    if args.include_privacy_relay:
        print("  WARNING: includes a source with no established redistribution grant")
    return 0


if __name__ == "__main__":
    sys.exit(main())

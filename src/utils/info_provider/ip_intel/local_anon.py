"""Anonymiser detection from bundled lists. No network, no credentials.

What this catches well, measured against ground truth resolved from the operators
themselves: Tor exits (effectively all of them, since the Tor Project publishes
its own exit list), and mainstream commercial VPNs (89-100% against Mullvad and
NordVPN server lists). What it does not catch is residential proxies, and no free
dataset does: 91% of such addresses live under ten days, so any bundled snapshot
is stale on arrival. That gap is documented rather than papered over.

Three design decisions carry most of the value:

**Graded labels, not a boolean.** "This address is in a data centre" and "this
address is a Tor exit" are different claims with different consequences, and
collapsing them is what produces false positives. ``is_vpn`` is still derived for
the existing scoring path, but the evidence travels alongside it.

**Suppression is an override, not a weight.** Apple iCloud Private Relay, CDNs and
corporate SASE egress all originate from hosting ranges. A measured 15.3% of
sampled Private Relay ranges are flagged by the naive lists, so without an
explicit "these are fine" layer evaluated first, a large population of ordinary
users looks like a VPN.

**Unchecked is not clean.** Coverage is tracked per label and per address family.
The Tor and VPN lists are IPv4-only, so for an IPv6 client only the ASN-backed
datacenter check can answer, and saying "clean" there would claim we looked for
Tor when we could not.
"""

import ipaddress
import json
import logging
import threading
import time
from pathlib import Path

from src.core.config.environment import (
    ANON_BUNDLE_DIR,
    ANON_DATACENTER_IS_VPN,
    IP_DATA_RELOAD_CHECK_SECONDS,
    IP_DATA_STALE_WARN_DAYS,
)
from src.utils.info_provider.ip_intel.base import (
    ALL_LABELS,
    DETECTION_LABELS,
    HIGH_CONFIDENCE_LABELS,
    MEDIUM_CONFIDENCE_LABELS,
    SUPPRESSION_LABELS,
    AnonymityResult,
    anonymity_unresolved,
)
from src.utils.info_provider.ip_intel.local_geo import lookup_asn
from src.utils.info_provider.ip_intel.ranges import IpRangeIndex

SOURCE = "bundled-lists"

# Confidence scores. Absolute values matter less than the ordering: a positive
# verdict from a high-confidence list outranks one inferred from hosting, and any
# verdict is weakened when the data behind it is old or incomplete.
_CONFIDENCE_HIGH = 95
_CONFIDENCE_HIGH_STALE = 70
_CONFIDENCE_MEDIUM = 65
_CONFIDENCE_MEDIUM_STALE = 50
_CONFIDENCE_CLEAN = 90
_CONFIDENCE_CLEAN_PARTIAL = 50
_SUPPRESSION_MISSING_PENALTY_HIGH = 20
_SUPPRESSION_MISSING_PENALTY_MEDIUM = 15


class AnonymiserIndex:
    """In-memory index over the bundled lists, reloaded when they change.

    Nothing here raises: a missing or corrupt bundle degrades the signal, because
    an authentication decision must never fail on the state of a data file.
    """

    def __init__(self, bundle_dir: str | None, check_interval: float | None = None):
        self._dir = Path(bundle_dir) if bundle_dir else None
        self._sets: dict[str, IpRangeIndex] = {}
        self._hosting_asns: set[int] = set()
        self._build_epoch: int | None = None
        self._stamp = None
        self._next_check = 0.0
        self._interval = (
            IP_DATA_RELOAD_CHECK_SECONDS if check_interval is None else check_interval
        )
        self._lock = threading.Lock()

    # -- loading ------------------------------------------------------------

    def _read_lines(self, filename: str) -> list[str]:
        return (self._dir / filename).read_text(encoding="utf-8").splitlines()

    def _load(self) -> None:
        manifest = json.loads((self._dir / "manifest.json").read_text(encoding="utf-8"))

        sets: dict[str, IpRangeIndex] = {}
        for label, filename in (manifest.get("lists") or {}).items():
            if label not in ALL_LABELS:
                # An unknown label would never be consulted by classify(), so
                # loading it would waste memory and hide a bundle/code mismatch.
                logging.warning("Ignoring unrecognised anonymiser list %r", label)
                continue
            try:
                sets[label] = IpRangeIndex.from_lines(self._read_lines(filename))
            except OSError as exc:
                logging.warning("Anonymiser list %s is unreadable: %s", filename, exc)

        asns: set[int] = set()
        asn_file = manifest.get("hosting_asns")
        if asn_file:
            try:
                for line in self._read_lines(asn_file):
                    token = line.strip().split("#", 1)[0].strip()
                    if not token:
                        continue
                    # Accept "AS15169", "15169", or "15169<tab>Org<tab>Country".
                    token = token.split()[0].lstrip("ASas")
                    if token.isdigit():
                        asns.add(int(token))
            except OSError as exc:
                logging.warning("Hosting ASN list %s is unreadable: %s", asn_file, exc)

        self._sets = sets
        self._hosting_asns = asns
        self._build_epoch = manifest.get("build_epoch")

        ipv6_labels = [label for label, index in sets.items() if index.covers_version(6)]
        logging.info(
            "Loaded anonymiser bundle: %s lists %s, %s hosting ASNs, %sd old, "
            "IPv6 range data for %s",
            len(sets),
            sorted(sets),
            len(asns),
            self.age_days(),
            ipv6_labels or "nothing",
        )

    def ensure_loaded(self) -> bool:
        """Load or reload if the manifest changed. False if nothing is available."""
        if self._dir is None:
            return False

        if self._sets and time.monotonic() < self._next_check:
            return True

        with self._lock:
            if self._sets and time.monotonic() < self._next_check:
                return True
            self._next_check = time.monotonic() + self._interval

            try:
                stat = (self._dir / "manifest.json").stat()
            except OSError:
                return bool(self._sets)  # keep serving a previously loaded bundle

            stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if stamp == self._stamp and self._sets:
                return True

            try:
                self._load()
                self._stamp = stamp
            except Exception as exc:
                logging.warning("Could not load anonymiser bundle: %s", exc)

            return bool(self._sets)

    # -- reporting ----------------------------------------------------------

    def age_days(self) -> int | None:
        """Whole days since the bundle was built, clamped at zero.

        Same caveat as ``MmdbHandle.age_days``: a build date ahead of this host's
        clock is indistinguishable here from a bundle built today.
        """
        if self._build_epoch is None:
            return None
        return max(0, int((time.time() - self._build_epoch) // 86400))

    def has_suppression_data(self) -> bool:
        return any(label in self._sets for label in SUPPRESSION_LABELS)

    def loaded_labels(self) -> list[str]:
        """Labels the bundle can currently evaluate, for health reporting."""
        return sorted(self._sets)

    def ipv6_labels(self) -> list[str]:
        """Labels with IPv6 range data, which is the honest coverage picture.

        Reported because the shipped lists are IPv4-only, so an operator reading
        health output should be able to see that an IPv6 client is evaluated by the
        ASN-backed check alone rather than by everything.
        """
        return sorted(
            label for label, index in self._sets.items() if index.covers_version(6)
        )

    def hosting_asn_count(self) -> int:
        return len(self._hosting_asns)

    # -- classification -----------------------------------------------------

    def classify(self, ip_address: str) -> AnonymityResult:
        """Graded classification of an address. Never raises."""
        try:
            address = ipaddress.ip_address(ip_address)
        except ValueError:
            return anonymity_unresolved("invalid-ip")

        # Checked BEFORE the bundle, because this answer needs no data. Covers
        # RFC1918, loopback, link-local and the reserved and documentation
        # ranges: none can be a real routed client address, so there is nothing
        # to look up and nothing to flag. Deciding this first means a deployment
        # with no bundle still classifies internal traffic correctly instead of
        # reporting it as unresolved.
        if not address.is_global:
            return {
                "labels": ["non_public"],
                "is_vpn": False,
                "confidence": 100,
                "list_age_days": None,
                "resolved": True,
                "unchecked": [],
                "source": "non-public-range",
            }

        if not self.ensure_loaded():
            return anonymity_unresolved("bundle-unavailable")

        labels = [
            label
            for label in ALL_LABELS
            if label in self._sets and self._sets[label].contains(address)
        ]

        # The ASN join recovers hosting ranges the CIDR lists miss, and is
        # unioned rather than substituted: each approach misses ranges the other
        # catches, so running both is worth the extra lookup.
        asn = lookup_asn(ip_address)[0]
        if "datacenter" not in labels and asn is not None and asn in self._hosting_asns:
            labels.append("datacenter")

        # Which labels could actually be evaluated for THIS address family?
        checked = {
            label
            for label, index in self._sets.items()
            if index.covers_version(address.version)
        }
        if asn is not None:
            checked.add("datacenter")
        unchecked = [label for label in ALL_LABELS if label not in checked]

        # Resolution depends on DETECTION coverage alone. Suppression data by
        # itself can never establish that an address is clean, so a bundle with
        # only suppression lists loaded has still checked nothing.
        if not any(label in checked for label in DETECTION_LABELS):
            return anonymity_unresolved(f"no-data-for-ipv{address.version}")

        suppressed = any(label in SUPPRESSION_LABELS for label in labels)
        high = [label for label in labels if label in HIGH_CONFIDENCE_LABELS]
        medium = [label for label in labels if label in MEDIUM_CONFIDENCE_LABELS]

        # Suppression wins outright: legitimate shared egress that happens to sit
        # in a hosting range is not an anonymiser.
        if suppressed:
            is_vpn = False
        elif high:
            is_vpn = True
        elif medium:
            is_vpn = ANON_DATACENTER_IS_VPN
        else:
            is_vpn = False

        return {
            "labels": labels,
            "is_vpn": is_vpn,
            "confidence": self._confidence(high, medium, checked),
            "list_age_days": self.age_days(),
            "resolved": True,
            "unchecked": unchecked,
            "source": SOURCE if not unchecked else f"{SOURCE}-partial",
        }

    def _confidence(self, high: list, medium: list, checked: set) -> int:
        """Grade the verdict by evidence strength, data age and coverage.

        Coverage is split by what a source can *do*, not merely counted. A
        detection source can raise a flag, so a missing one weakens a "clean"
        verdict. A suppression source can only clear a flag, so a missing one
        cannot cause a false negative, but it does weaken a *positive* verdict
        because legitimate shared egress can no longer be ruled out.
        """
        age = self.age_days()
        stale = age is not None and age > IP_DATA_STALE_WARN_DAYS

        missing_suppression = [
            label for label in SUPPRESSION_LABELS if label not in checked
        ]
        missing_detection = [label for label in DETECTION_LABELS if label not in checked]

        if high:
            score = _CONFIDENCE_HIGH_STALE if stale else _CONFIDENCE_HIGH
            if missing_suppression:
                score -= _SUPPRESSION_MISSING_PENALTY_HIGH
            return score

        if medium:
            score = _CONFIDENCE_MEDIUM_STALE if stale else _CONFIDENCE_MEDIUM
            if missing_suppression:
                score -= _SUPPRESSION_MISSING_PENALTY_MEDIUM
            return score

        # Nothing matched. Missing suppression data is irrelevant to a clean
        # verdict; missing detection data is exactly what makes it weaker.
        return _CONFIDENCE_CLEAN_PARTIAL if missing_detection else _CONFIDENCE_CLEAN


INDEX = AnonymiserIndex(ANON_BUNDLE_DIR)


def log_startup_state() -> None:
    if not INDEX.ensure_loaded():
        logging.warning(
            "Anonymiser bundle not available at %s: the anonymous-detection "
            "signal cannot contribute to risk scoring.",
            ANON_BUNDLE_DIR,
        )
        return

    if ANON_DATACENTER_IS_VPN and not INDEX.has_suppression_data():
        logging.warning(
            "ANON_DATACENTER_IS_VPN is enabled but no suppression list is "
            "loaded. Legitimate shared egress such as Apple iCloud Private "
            "Relay, CDNs and corporate SASE lives in hosting ranges and will be "
            "reported as a VPN; a measured 15.3%% of sampled Private Relay "
            "ranges are affected."
        )

# Seed IP intelligence data

Fallback copies of the upstream sources, committed so that
`scripts/build_ip_bundle.py --offline` produces a working bundle on a host with no
internet access. They are a last resort: a connected build always prefers fresh
downloads, and an operator-staged `--source-dir` always wins over both.

## What is here, and what is deliberately not

| File | Size | Licence | Upstream |
|---|---|---|---|
| `torbulkexitlist` | 19 KB | CC0 | <https://check.torproject.org/torbulkexitlist> |
| `x4bnet-vpn-ipv4.txt` | 185 KB | MIT | X4BNet/lists_vpn `output/vpn/ipv4.txt` |
| `x4bnet-datacenter-ipv4.txt` | 664 KB | MIT | X4BNet/lists_vpn `output/datacenter/ipv4.txt` |
| `x4bnet-datacenter-ASN.txt` | 31 KB | MIT | X4BNet/lists_vpn `input/datacenter/ASN.txt` |
| `country_centroids.csv` | 5 KB | CC BY 4.0 | derived from DB-IP City Lite |

Every licence here permits redistribution, which is why these sources were chosen
over the alternatives; see the `NOTICE` written into each built bundle for the
full attribution text.

**The geolocation databases are not committed.** DB-IP Lite country and ASN are
4.0 MB and 5.2 MB compressed, and city is 62 MB, which does not belong in git
history where every refresh would add another copy permanently. An offline build
without them still gives working anonymiser detection (Tor, commercial VPN,
hosting ranges by CIDR), but no country, no coordinates and no ASN lookup, and the
engine logs that at startup.

To get geolocation on an air-gapped host, stage the databases instead:

```bash
# On a connected host
python scripts/build_ip_bundle.py --out /tmp/throwaway --with-city --save-sources staged/

# Transfer staged/ to the air-gapped host, then
python scripts/build_ip_bundle.py --out bundle --with-city --keep-city --offline --source-dir staged/
```

## Refreshing the seed

These files age. The engine already accounts for that: bundle age reduces the
confidence attached to a positive verdict, and the build prints a warning when any
artefact came from the seed. Refresh with

```bash
python scripts/build_ip_bundle.py --out /tmp/throwaway --with-city --save-sources /tmp/staged
cp /tmp/staged/torbulkexitlist /tmp/staged/x4bnet-*.txt ipdata/seed/
cp /tmp/throwaway/country_centroids.csv ipdata/seed/
```

The X4BNet lists are pinned to the commit recorded in `build_ip_bundle.py`
(`X4BNET_COMMIT`), because that project's MIT grant lives in its README rather
than a LICENSE file. Re-read that licence section when moving the pin.

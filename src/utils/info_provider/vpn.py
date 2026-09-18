"""Anonymiser (VPN / proxy / Tor) lookup, kept at its historical import path.

A thin shim over the provider registry in ``src.utils.info_provider.ip_intel``.
The function name and the ``is_vpn`` key are unchanged, so
``risk_evaluation/checks/anonymous_detection.py``, the log-odds scoring and the
database schema need no edits.

The richer graded result travels alongside as additive keys, for logs and for
explaining a decision. ``is_vpn`` stays the single boolean the scoring path
consumes.
"""

from src.utils.info_provider.ip_intel import resolve_anonymity
from src.utils.info_provider.ip_intel.base import AnonymityResult


def to_legacy_shape(ip_address: str, result: AnonymityResult) -> dict:
    """Map the provider contract onto the historical dict."""
    return {
        "ip_address": ip_address,
        "is_vpn": bool(result.get("is_vpn")),
        # Additive: which evidence matched, how confident, and how old the data
        # was.
        "anon_labels": result.get("labels", []),
        "anon_confidence": result.get("confidence", 0),
        "anon_list_age_days": result.get("list_age_days"),
        # Labels that could not be evaluated for this address family. A non-empty
        # value means "clean" is only as strong as the sources we could consult:
        # the bundled Tor and VPN lists are IPv4-only, so for an IPv6 address only
        # the ASN-backed datacenter check can answer.
        "anon_unchecked": result.get("unchecked", []),
        # False means nothing was checked, rather than "clean". That distinction
        # is what keeps an uncovered address from being reported as safe.
        "resolved": bool(result.get("resolved")),
        "source": result.get("source", "unknown"),
    }


async def get_cached_vpn_info(ip_address: str) -> dict:
    """Resolve anonymiser status for an address.

    Named "cached" for historical reasons; see ``geoloc.get_cached_geo_info``.
    """
    return to_legacy_shape(ip_address, await resolve_anonymity(ip_address))

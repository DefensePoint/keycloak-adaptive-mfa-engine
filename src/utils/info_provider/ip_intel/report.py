"""One description of IP data state, shared by every consumer.

``/health`` and the startup log both read this, so the two cannot disagree about
what loaded and how old it is. That matters more than it sounds: an air-gap
reviewer compares the startup log against the health endpoint, and two independent
formatters drift apart until they contradict each other.

**Nothing here raises, and nothing here affects readiness.** A snapshot is a
description of data files, and the age of a data file is not a reason to fail a
health check or refuse a login. Reporting is one-directional: it can tell an
operator the geo signal is degraded, never take the service out of rotation for it.
"""

import logging

from src.core.config.environment import (
    ANON_BUNDLE_DIR,
    ANON_DATACENTER_IS_VPN,
    IP_DATA_STALE_WARN_DAYS,
)
from src.utils.info_provider.ip_intel import local_anon, local_geo

# Reported so the caller does not have to infer the posture from an empty field.
EGRESS_NONE = "none"


def _edition(label: str, handle) -> dict:
    """State of one MMDB edition. Never raises."""
    try:
        loaded = handle.reader() is not None
        return {
            "loaded": loaded,
            "path": handle.path,
            "age_days": handle.age_days() if loaded else None,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logging.debug("Could not describe IP database [%s]: %s", label, exc)
        return {"loaded": False, "path": None, "age_days": None}


def _geo() -> dict:
    editions = {
        "country": _edition("country", local_geo.COUNTRY),
        "city": _edition("city", local_geo.CITY),
        "asn": _edition("asn", local_geo.ASN),
    }

    # Which source would actually supply a coordinate. Stated explicitly because
    # "city" versus "country-centroid" is the difference between impossible-travel
    # seeing real distance and seeing zero for every move inside a country.
    if editions["city"]["loaded"]:
        coordinates = "city-db"
    elif local_geo.CENTROIDS.available():
        coordinates = "country-centroid"
    else:
        coordinates = "none"

    return {"editions": editions, "coordinates": coordinates}


def _anonymiser() -> dict:
    index = local_anon.INDEX
    try:
        loaded = index.ensure_loaded()
    except Exception as exc:  # pragma: no cover - ensure_loaded already swallows
        logging.debug("Could not load anonymiser bundle for reporting: %s", exc)
        loaded = False

    if not loaded:
        return {
            "loaded": False,
            "path": ANON_BUNDLE_DIR,
            "age_days": None,
            "labels": [],
            "ipv6_labels": [],
            "hosting_asns": 0,
            "suppression_data": False,
            "datacenter_is_vpn": bool(ANON_DATACENTER_IS_VPN),
        }

    return {
        "loaded": True,
        "path": ANON_BUNDLE_DIR,
        "age_days": index.age_days(),
        "labels": index.loaded_labels(),
        "ipv6_labels": index.ipv6_labels(),
        "hosting_asns": index.hosting_asn_count(),
        "suppression_data": index.has_suppression_data(),
        "datacenter_is_vpn": bool(ANON_DATACENTER_IS_VPN),
    }


def _assess(geo: dict, anonymiser: dict) -> tuple[str, list[str]]:
    """A summary word plus the reasons behind it. Advisory only.

    Deliberately not a health verdict. "degraded" here means a risk signal cannot
    contribute, which is a thing to tell an operator, not a reason to drain traffic
    from an engine that is authenticating people correctly without it.
    """
    notes = []

    if not geo["editions"]["country"]["loaded"]:
        notes.append("no country database: country rules cannot match")
    if geo["coordinates"] == "none":
        notes.append(
            "no coordinate source: impossible-travel and geo-clustering inactive"
        )
    if not anonymiser["loaded"]:
        notes.append("no anonymiser bundle: VPN and Tor detection inactive")

    stale = [
        name
        for name, state in geo["editions"].items()
        if (state.get("age_days") or 0) > IP_DATA_STALE_WARN_DAYS
    ]
    if (anonymiser.get("age_days") or 0) > IP_DATA_STALE_WARN_DAYS:
        stale.append("anonymiser")
    if stale:
        notes.append(
            f"older than {IP_DATA_STALE_WARN_DAYS} days: " + ", ".join(sorted(stale))
        )

    if not geo["editions"]["country"]["loaded"] and not anonymiser["loaded"]:
        return "unavailable", notes
    return ("degraded" if notes else "ok"), notes


def status_only() -> dict:
    """The single summary word from snapshot(), nothing else.

    For the unauthenticated /health response. snapshot()'s full detail --
    absolute filesystem paths, database ages, loaded-category labels, hosting
    ASN counts, IPv6 coverage flags -- is an operational map of the deployment
    handed to anyone who can reach the service: which detections are
    currently inactive or degraded, and therefore which evasion routes carry
    no penalty, before a single attempt is made. "ok"/"degraded"/"unavailable"/
    "unknown" alone does not carry that specificity. Callers that need the
    full inventory use the authenticated detail endpoint instead, which
    still calls snapshot() directly.
    """
    try:
        geo = _geo()
        anonymiser = _anonymiser()
        status, _notes = _assess(geo, anonymiser)
        return {"status": status}
    except Exception as exc:
        logging.warning("Could not build the IP data status: %s", exc)
        return {"status": "unknown"}


def snapshot() -> dict:
    """Current IP data state. Never raises, never affects readiness."""
    try:
        geo = _geo()
        anonymiser = _anonymiser()
        status, notes = _assess(geo, anonymiser)
        return {
            "status": status,
            "egress": EGRESS_NONE,
            "geo": geo,
            "anonymiser": anonymiser,
            "notes": notes,
        }
    except Exception as exc:
        # The endpoint that calls this must still answer. A reporting bug is not an
        # outage, so it degrades to "unknown" rather than propagating.
        logging.warning("Could not build the IP data snapshot: %s", exc)
        return {
            "status": "unknown",
            "egress": EGRESS_NONE,
            "geo": {},
            "anonymiser": {},
            "notes": ["snapshot unavailable"],
        }

"""IP intelligence: geolocation and anonymiser detection from local data.

Everything is resolved from databases and CIDR lists shipped inside the image and
read from disk. There is no third-party API and no outbound connection on the
authentication path, which is what makes on-premise and air-gapped deployment
possible. The previous design called an external service for every uncached
lookup, so an isolated site could not use these signals at all.

The consequences of having no network in this path are worth stating, because
they remove whole classes of problem rather than merely relocating them:

* No lookup can time out, so no login is delayed by someone else's outage.
* No failure needs caching, so a transient error cannot be remembered as a fact.
* There is no API key to hold, rotate, or leak, and no per-day call ceiling that
  a busy hour can exhaust.
* Nothing about a user's address is disclosed to a third party in order to
  evaluate it.

What it costs is freshness and precision: the data is a snapshot, and it is only
as good as its last refresh. That trade is handled explicitly rather than hidden,
by reporting coverage and age alongside every verdict (see ``base.py``), and by
never letting the age of a file block an authentication.

An operator who wants different data supplies their own file at the same paths
(``GEOIP_*_PATH``, ``ANON_BUNDLE_DIR``). MMDB is a shared format, so a MaxMind or
other commercial database drops straight in, with the licence obligation staying
with whoever holds it.
"""

import logging

from src.utils.info_provider.ip_intel import local_anon, local_geo
from src.utils.info_provider.ip_intel.base import AnonymityResult, GeoResult

SOURCE = "bundled"


async def resolve_geo(ip_address: str) -> GeoResult:
    """Resolve geolocation for an address.

    Declared async to match the call sites, which await it. The lookup itself is
    synchronous by nature: there is no socket, just an in-memory database read,
    which completes faster than scheduling a coroutine would cost.
    """
    return local_geo.lookup(ip_address)


async def resolve_anonymity(ip_address: str) -> AnonymityResult:
    """Resolve anonymiser (VPN / proxy / Tor) status for an address."""
    return local_anon.INDEX.classify(ip_address)


def log_startup_state() -> None:
    """Report what data actually loaded, before the first login rather than after.

    "The bundle is missing" is the difference between a working risk signal and
    one that silently cannot contribute, so it belongs in the startup log.
    """
    logging.info("IP intelligence: local data only, no outbound calls")
    local_geo.log_startup_state()
    local_anon.log_startup_state()

    # The same snapshot `/health` serves. Logged here so the two cannot disagree,
    # and so a fault in the snapshot surfaces at boot rather than at whatever
    # moment someone first polls the endpoint.
    from src.utils.info_provider.ip_intel import report

    state = report.snapshot()
    logging.info(
        "IP data: %s, coordinates from %s, egress %s",
        state["status"],
        state.get("geo", {}).get("coordinates", "unknown"),
        state["egress"],
    )
    for note in state.get("notes", []):
        logging.warning("IP data: %s", note)

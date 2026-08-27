"""Geolocation lookup, kept at its historical import path.

A thin shim over the provider registry in ``src.utils.info_provider.ip_intel``.
The function name and the returned dict shape are unchanged, so
``data/factory/network_location.py``, ``data/factory/auth_process.py`` and every
risk check need no edits.

Two details of the legacy contract are load-bearing and deliberately preserved:

* **Unresolved coordinates are reported as ``0``, not ``None``.**
  ``risk_evaluation/checks/impossible_travel.py`` raises ``ValueError`` on a
  ``None`` coordinate and uses ``(0, 0)`` as its "not geolocatable" sentinel, and
  ``ClusteringService.get_geo_cluster_label`` filters history on the same
  sentinel. Emitting ``None`` here would turn a benign unknown location into an
  exception on the authentication path.

* **``country_name`` carries the ISO alpha-2 code, not the display name.** The
  historical provider returned its ``country`` field (an ISO code) under this key, admins configure
  country allow/deny lists with the code (``country_name`` is in
  ``ALLOWED_BLACK_WHITE_LIST_PARAMS``), and stored history holds the code.
  Returning "United States" where the data says "US" would silently stop every
  configured country rule from matching.
"""

from src.utils.info_provider.ip_intel import resolve_geo
from src.utils.info_provider.ip_intel.base import GeoResult


def to_legacy_shape(ip_address: str, result: GeoResult) -> dict:
    """Map the provider contract onto the historical dict."""
    resolved = bool(result.get("resolved"))
    lat = result.get("lat") if resolved else 0
    long = result.get("long") if resolved else 0

    return {
        "ip_address": ip_address,
        "lat": lat,
        "long": long,
        "geolocation": (lat, long),
        "country_name": result.get("country_iso") or "",
        "city_name": result.get("city_name") or "",
        # Additive, for logs and explainability. Existing consumers read by key
        # and are unaffected by these.
        "resolved": resolved,
        "coordinate_source": result.get("coordinate_source", "none"),
        "source": result.get("source", "unknown"),
    }


async def get_cached_geo_info(ip_address: str) -> dict:
    """Resolve geolocation for an address.

    Named "cached" for historical reasons; the name is kept because two factories
    import it. The bundled provider needs no cache, since an in-memory database
    lookup is faster than a Redis round trip. The opt-in API provider keeps its
    own Redis cache.
    """
    return to_legacy_shape(ip_address, await resolve_geo(ip_address))

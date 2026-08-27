"""Geolocation from bundled databases. No network, no credentials.

Reads DB-IP Lite MMDB files shipped inside the image. There is no socket in this
path, so unlike an HTTP lookup it cannot time out, and no failure can be cached:
both of which remove whole classes of problem the API-backed design had.

DB-IP Lite uses the same record schema as GeoLite2, so the key paths below also
work against an operator-supplied MaxMind database (the bring-your-own-MMDB
path), where the licence obligation stays with the operator who holds it.

Coordinate precedence is city database, then country centroid. When neither can
answer, the result is ``resolved=False`` and the caller must not read the
coordinates as a position.
"""

import logging

from src.core.config.environment import (
    GEOIP_ASN_PATH,
    GEOIP_CITY_PATH,
    GEOIP_COUNTRY_PATH,
)
from src.utils.info_provider.ip_intel.base import GeoResult, geo_unresolved
from src.utils.info_provider.ip_intel.centroids import CENTROIDS
from src.utils.info_provider.ip_intel.mmdb import MmdbHandle

COUNTRY = MmdbHandle(GEOIP_COUNTRY_PATH)
CITY = MmdbHandle(GEOIP_CITY_PATH)  # optional; None-safe
ASN = MmdbHandle(GEOIP_ASN_PATH)

SOURCE = "bundled-db"


def _english_name(node) -> str:
    """The English display name from an MMDB names map, or ''.

    Defensive about shape because these are third-party files: a record that is
    not the expected nested-dict form must degrade, not raise.
    """
    if not isinstance(node, dict):
        return ""
    names = node.get("names")
    return names.get("en") or "" if isinstance(names, dict) else ""


def _country_from(record) -> tuple[str | None, str]:
    """(iso_code, display_name) from a record's country node."""
    if not isinstance(record, dict):
        return (None, "")
    # registered_country is the fallback for addresses with no assigned
    # geographic country, which is common for anycast and some cloud ranges.
    node = record.get("country") or record.get("registered_country")
    if not isinstance(node, dict):
        return (None, "")
    return (node.get("iso_code"), _english_name(node))


def lookup_asn(ip_address: str) -> tuple[int | None, str | None]:
    """(asn, organisation) for an address, or (None, None).

    The ASN is used two ways: as the `asn` risk signal, and to decide whether an
    address lives in a hosting provider's network, which the anonymiser detection
    unions with its CIDR lists.
    """
    record = ASN.get(ip_address)
    if not isinstance(record, dict):
        return (None, None)
    asn = record.get("autonomous_system_number")
    organisation = record.get("autonomous_system_organization")
    # Guard the type: a non-int here would reach a set-membership test against
    # integer ASNs and silently never match.
    return (asn if isinstance(asn, int) else None, organisation or None)


def lookup(ip_address: str) -> GeoResult:
    """Resolve an address against the bundled databases. Never raises."""
    country_iso = None
    country_display_name = ""
    city_name = ""
    lat = None
    long = None

    city_record = CITY.get(ip_address)
    if isinstance(city_record, dict):
        location = city_record.get("location")
        if isinstance(location, dict):
            lat = location.get("latitude")
            long = location.get("longitude")
        city_name = _english_name(city_record.get("city"))
        country_iso, country_display_name = _country_from(city_record)

    if country_iso is None:
        country_iso, country_display_name = _country_from(COUNTRY.get(ip_address))

    coordinate_source = "city-db"
    if lat is None or long is None:
        lat, long = CENTROIDS.get(country_iso)
        coordinate_source = "country-centroid"

    if lat is None or long is None:
        # Country may still be known; only the position is missing. The shim maps
        # this to the (0, 0) sentinel the existing checks already understand.
        result = geo_unresolved(SOURCE)
        result["country_iso"] = country_iso
        result["country_display_name"] = country_display_name
        result["city_name"] = city_name
        return result

    return {
        "lat": lat,
        "long": long,
        "country_iso": country_iso,
        "country_display_name": country_display_name,
        "city_name": city_name,
        "resolved": True,
        "coordinate_source": coordinate_source,
        "source": SOURCE,
    }


def data_available() -> bool:
    """Whether any geo database is loaded, for health reporting."""
    return COUNTRY.reader() is not None or CITY.reader() is not None


def age_days() -> int | None:
    """Age of the most precise loaded database, in whole days."""
    return CITY.age_days() if CITY.reader() is not None else COUNTRY.age_days()


def log_startup_state() -> None:
    """One line per edition, so an operator can see what actually loaded."""
    for label, handle in (("country", COUNTRY), ("city", CITY), ("asn", ASN)):
        if handle.reader() is None:
            logging.info("IP geo database [%s]: not configured or unavailable", label)
        else:
            logging.info(
                "IP geo database [%s]: loaded, %sd old", label, handle.age_days()
            )

    if CITY.reader() is None and not CENTROIDS.available():
        logging.warning(
            "No city database and no country centroid table: coordinates are "
            "unavailable, so impossible-travel and geo-clustering cannot "
            "contribute to risk scoring."
        )

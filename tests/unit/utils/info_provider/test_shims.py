"""The legacy dict shapes that ``geoloc`` and ``vpn`` must keep emitting.

These two modules are now thin shims over the provider registry, and their
historical return shape is load-bearing for code well outside this package. The
assertions here are what stop a provider refactor from silently breaking risk
scoring, so each one records *why* the shape matters rather than merely that it
is the shape.
"""

import pytest

from src.utils.info_provider import geoloc, vpn
from src.utils.info_provider.ip_intel.base import geo_unresolved, anonymity_unresolved

LEGACY_GEO_KEYS = {"ip_address", "lat", "long", "geolocation", "country_name", "city_name"}
LEGACY_VPN_KEYS = {"ip_address", "is_vpn"}

RESOLVED_GEO = {
    "lat": 37.4056,
    "long": -122.0775,
    "country_iso": "US",
    "country_display_name": "United States",
    "city_name": "Mountain View",
    "resolved": True,
    "coordinate_source": "city-db",
    "source": "bundled-db",
}


# -- geolocation -----------------------------------------------------------


def test_resolved_geo_keeps_every_legacy_key():
    result = geoloc.to_legacy_shape("8.8.8.8", RESOLVED_GEO)

    assert LEGACY_GEO_KEYS <= set(result)
    assert result["ip_address"] == "8.8.8.8"
    assert result["lat"] == 37.4056
    assert result["long"] == -122.0775
    assert result["geolocation"] == (37.4056, -122.0775)
    assert result["city_name"] == "Mountain View"


def test_country_name_carries_the_iso_code_not_the_display_name():
    """Admins configure country rules with the two-letter code.

    The historical provider returned its ``country`` field (an ISO code) under
    this key, ``country_name`` is in ALLOWED_BLACK_WHITE_LIST_PARAMS, and stored
    history holds codes. Emitting "United States" here would silently stop every
    configured country rule from matching, and it would fail open.
    """
    result = geoloc.to_legacy_shape("8.8.8.8", RESOLVED_GEO)

    assert result["country_name"] == "US"


def test_unresolved_coordinates_are_zero_not_none():
    """``impossible_travel`` raises ValueError on a None coordinate.

    It uses (0, 0) as its "not geolocatable" sentinel, and
    ClusteringService.get_geo_cluster_label filters history on the same value.
    Emitting None would turn a benign unknown location into an exception on the
    authentication path.
    """
    result = geoloc.to_legacy_shape("10.0.0.1", geo_unresolved("bundled-db"))

    assert result["lat"] == 0
    assert result["long"] == 0
    assert result["geolocation"] == (0, 0)
    assert result["lat"] is not None
    assert result["long"] is not None


def test_unresolved_geo_uses_empty_strings_for_names():
    result = geoloc.to_legacy_shape("10.0.0.1", geo_unresolved("bundled-db"))

    assert result["country_name"] == ""
    assert result["city_name"] == ""


def test_a_resolved_country_without_coordinates_still_reports_zero():
    """Partial resolution must not leak a half-populated coordinate.

    A provider can know the country but not the position. Since `resolved` is
    False, the coordinate has to fall back to the sentinel rather than be passed
    through as None.
    """
    partial = dict(geo_unresolved("bundled-db"), country_iso="US")

    result = geoloc.to_legacy_shape("1.2.3.4", partial)

    assert result["lat"] == 0
    assert result["long"] == 0
    assert result["country_name"] == "US"


def test_geolocation_tuple_always_matches_the_scalar_fields():
    for source in (RESOLVED_GEO, geo_unresolved("bundled-db")):
        result = geoloc.to_legacy_shape("1.2.3.4", source)
        assert result["geolocation"] == (result["lat"], result["long"])


@pytest.mark.asyncio
async def test_get_cached_geo_info_returns_the_legacy_shape(monkeypatch):
    async def fake_resolve(ip_address):
        return RESOLVED_GEO

    monkeypatch.setattr(geoloc, "resolve_geo", fake_resolve)

    result = await geoloc.get_cached_geo_info("8.8.8.8")

    assert LEGACY_GEO_KEYS <= set(result)
    assert result["country_name"] == "US"


# -- anonymiser ------------------------------------------------------------


def test_vpn_keeps_the_legacy_boolean():
    resolved = {
        "labels": ["tor_exit"],
        "is_vpn": True,
        "confidence": 95,
        "list_age_days": 3,
        "resolved": True,
        "unchecked": [],
        "source": "bundled-lists",
    }

    result = vpn.to_legacy_shape("1.2.3.4", resolved)

    assert LEGACY_VPN_KEYS <= set(result)
    assert result["ip_address"] == "1.2.3.4"
    assert result["is_vpn"] is True


def test_unresolved_anonymity_reports_false_not_an_error():
    """Fail open on the boolean, but say so in `resolved`.

    The scoring path consumes `is_vpn` and must get a usable boolean; anything
    reading the richer keys can tell the difference between "checked and clean"
    and "not checked".
    """
    result = vpn.to_legacy_shape("1.2.3.4", anonymity_unresolved("bundle-unavailable"))

    assert result["is_vpn"] is False
    assert result["resolved"] is False


def test_is_vpn_is_always_a_real_bool():
    """The database column and the log-odds scoring both expect a bool."""
    for value in (True, False, None, 1, 0, "", "yes"):
        result = vpn.to_legacy_shape("1.2.3.4", {"is_vpn": value})
        assert isinstance(result["is_vpn"], bool)


def test_evidence_travels_alongside_the_boolean():
    resolved = {
        "labels": ["datacenter"],
        "is_vpn": False,
        "confidence": 65,
        "list_age_days": 12,
        "resolved": True,
        "unchecked": ["privacy_relay"],
        "source": "bundled-lists-partial",
    }

    result = vpn.to_legacy_shape("1.2.3.4", resolved)

    assert result["anon_labels"] == ["datacenter"]
    assert result["anon_confidence"] == 65
    assert result["anon_list_age_days"] == 12
    assert result["anon_unchecked"] == ["privacy_relay"]
    assert result["source"] == "bundled-lists-partial"


def test_missing_optional_keys_do_not_raise():
    """A provider returning a minimal dict must not break the shim."""
    result = vpn.to_legacy_shape("1.2.3.4", {})

    assert result["is_vpn"] is False
    assert result["anon_labels"] == []
    assert result["anon_confidence"] == 0
    assert result["resolved"] is False


@pytest.mark.asyncio
async def test_get_cached_vpn_info_returns_the_legacy_shape(monkeypatch):
    async def fake_resolve(ip_address):
        return anonymity_unresolved("bundle-unavailable")

    monkeypatch.setattr(vpn, "resolve_anonymity", fake_resolve)

    result = await vpn.get_cached_vpn_info("1.2.3.4")

    assert LEGACY_VPN_KEYS <= set(result)
    assert result["is_vpn"] is False

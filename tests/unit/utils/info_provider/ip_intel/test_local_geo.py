"""Bundled geolocation: coordinate precedence and defensive record handling.

The MMDB records are stubbed rather than read from a real database, so the tests
pin the precedence and degradation rules without depending on a bundle being
present or on any particular vendor's data for a given address.
"""

import pytest

from src.utils.info_provider.ip_intel import local_geo
from src.utils.info_provider.ip_intel.base import GEO_RESULT_KEYS

CITY_RECORD = {
    "location": {"latitude": 37.4056, "longitude": -122.0775},
    "city": {"names": {"en": "Mountain View"}},
    "country": {"iso_code": "US", "names": {"en": "United States"}},
}
COUNTRY_RECORD = {"country": {"iso_code": "DE", "names": {"en": "Germany"}}}


@pytest.fixture
def stub_databases(monkeypatch):
    """Replace the three module-level handles with controllable stubs."""

    class Handle:
        def __init__(self):
            self.record = None

        def get(self, ip_address):
            return self.record

        def reader(self):
            return object() if self.record is not None else None

        def age_days(self):
            return 7

    handles = {name: Handle() for name in ("COUNTRY", "CITY", "ASN")}
    for name, handle in handles.items():
        monkeypatch.setattr(local_geo, name, handle)
    return handles


@pytest.fixture
def centroids(monkeypatch):
    class Centroids:
        def __init__(self):
            self.table = {"DE": (51.1657, 10.4515)}

        def get(self, country_iso):
            return self.table.get(country_iso, (None, None))

        def available(self):
            return bool(self.table)

    stub = Centroids()
    monkeypatch.setattr(local_geo, "CENTROIDS", stub)
    return stub


# -- coordinate precedence -------------------------------------------------


def test_city_database_wins_when_it_has_a_position(stub_databases, centroids):
    stub_databases["CITY"].record = CITY_RECORD
    stub_databases["COUNTRY"].record = COUNTRY_RECORD

    result = local_geo.lookup("8.8.8.8")

    assert result["lat"] == 37.4056
    assert result["long"] == -122.0775
    assert result["coordinate_source"] == "city-db"
    assert result["city_name"] == "Mountain View"
    assert result["country_iso"] == "US"  # the city record's country, not DE
    assert result["resolved"] is True
    assert set(result) == GEO_RESULT_KEYS


def test_country_centroid_is_used_when_there_is_no_city_database(
    stub_databases, centroids
):
    """The country-only configuration, which is the shipped default."""
    stub_databases["COUNTRY"].record = COUNTRY_RECORD

    result = local_geo.lookup("1.2.3.4")

    assert result["lat"] == 51.1657
    assert result["long"] == 10.4515
    assert result["coordinate_source"] == "country-centroid"
    assert result["country_iso"] == "DE"
    assert result["city_name"] == ""
    assert result["resolved"] is True


def test_centroid_fills_in_when_the_city_record_lacks_a_position(
    stub_databases, centroids
):
    stub_databases["CITY"].record = {
        "city": {"names": {"en": "Somewhere"}},
        "country": {"iso_code": "DE", "names": {"en": "Germany"}},
    }

    result = local_geo.lookup("1.2.3.4")

    assert result["coordinate_source"] == "country-centroid"
    assert result["lat"] == 51.1657
    assert result["city_name"] == "Somewhere"


def test_known_country_without_a_centroid_is_unresolved_but_keeps_the_country(
    stub_databases, centroids
):
    """Partial knowledge is reported as such.

    Country rules can still match on the ISO code, while impossible-travel and
    geo-clustering must not treat the missing position as a real coordinate.
    """
    stub_databases["COUNTRY"].record = {"country": {"iso_code": "AQ", "names": {}}}

    result = local_geo.lookup("1.2.3.4")

    assert result["resolved"] is False
    assert result["country_iso"] == "AQ"
    assert set(result) == GEO_RESULT_KEYS


def test_nothing_found_is_unresolved(stub_databases, centroids):
    result = local_geo.lookup("10.0.0.1")

    assert result["resolved"] is False
    assert result["country_iso"] is None
    assert set(result) == GEO_RESULT_KEYS


# -- defensive record handling ---------------------------------------------


def test_registered_country_is_the_fallback(stub_databases, centroids):
    """Anycast and some cloud ranges have no assigned geographic country."""
    stub_databases["COUNTRY"].record = {
        "registered_country": {"iso_code": "DE", "names": {"en": "Germany"}}
    }

    result = local_geo.lookup("1.2.3.4")

    assert result["country_iso"] == "DE"


@pytest.mark.parametrize(
    "record",
    [None, "unexpected", 42, [], {}, {"country": None}, {"country": "US"}],
)
def test_malformed_records_degrade_rather_than_raise(stub_databases, centroids, record):
    """These are third-party files; a surprising record must not break auth."""
    stub_databases["COUNTRY"].record = record
    stub_databases["CITY"].record = record

    result = local_geo.lookup("1.2.3.4")

    assert result["resolved"] is False
    assert set(result) == GEO_RESULT_KEYS


def test_missing_english_name_is_an_empty_string(stub_databases, centroids):
    stub_databases["COUNTRY"].record = {
        "country": {"iso_code": "DE", "names": {"fr": "Allemagne"}}
    }

    result = local_geo.lookup("1.2.3.4")

    assert result["country_iso"] == "DE"
    assert result["country_display_name"] == ""


# -- ASN -------------------------------------------------------------------


def test_asn_is_returned_with_its_organisation(stub_databases):
    stub_databases["ASN"].record = {
        "autonomous_system_number": 15169,
        "autonomous_system_organization": "GOOGLE",
    }

    assert local_geo.lookup_asn("8.8.8.8") == (15169, "GOOGLE")


def test_missing_asn_record_is_none(stub_databases):
    assert local_geo.lookup_asn("10.0.0.1") == (None, None)


@pytest.mark.parametrize("value", ["15169", 15169.0, None, [15169]])
def test_non_integer_asn_is_rejected(stub_databases, value):
    """A string ASN would reach a set-membership test against integers.

    It would never match, so hosting detection would silently stop working
    rather than fail loudly.
    """
    stub_databases["ASN"].record = {
        "autonomous_system_number": value,
        "autonomous_system_organization": "X",
    }

    assert local_geo.lookup_asn("1.2.3.4")[0] is None


def test_empty_organisation_becomes_none(stub_databases):
    stub_databases["ASN"].record = {
        "autonomous_system_number": 1,
        "autonomous_system_organization": "",
    }

    assert local_geo.lookup_asn("1.2.3.4") == (1, None)


# -- reporting -------------------------------------------------------------


def test_data_available_reflects_the_loaded_databases(stub_databases):
    assert local_geo.data_available() is False

    stub_databases["COUNTRY"].record = COUNTRY_RECORD
    assert local_geo.data_available() is True


def test_startup_warns_when_no_coordinate_source_exists(
    stub_databases, monkeypatch, caplog
):
    class NoCentroids:
        def get(self, country_iso):
            return (None, None)

        def available(self):
            return False

    monkeypatch.setattr(local_geo, "CENTROIDS", NoCentroids())
    stub_databases["COUNTRY"].record = COUNTRY_RECORD

    caplog.set_level("WARNING")
    local_geo.log_startup_state()

    assert "impossible-travel" in caplog.text

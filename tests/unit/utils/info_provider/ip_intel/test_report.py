"""The shared IP data snapshot.

Two properties matter more than the field list: it never raises, and it never
becomes a readiness verdict. Everything else is presentation.
"""

import pytest

from src.utils.info_provider.ip_intel import report


class StubHandle:
    def __init__(self, loaded=True, age=5, path="/opt/amfa/ipdata/x.mmdb"):
        self._loaded = loaded
        self._age = age
        self.path = path

    def reader(self):
        return object() if self._loaded else None

    def age_days(self):
        return self._age


class StubCentroids:
    def __init__(self, available=True):
        self._available = available

    def available(self):
        return self._available


class StubIndex:
    def __init__(self, loaded=True, age=3, labels=None, suppression=False):
        self._loaded = loaded
        self._age = age
        self._labels = labels if labels is not None else ["datacenter", "tor_exit"]
        self._suppression = suppression

    def ensure_loaded(self):
        return self._loaded

    def age_days(self):
        return self._age

    def loaded_labels(self):
        return self._labels

    def ipv6_labels(self):
        return []

    def hosting_asn_count(self):
        return 906

    def has_suppression_data(self):
        return self._suppression


@pytest.fixture
def healthy(monkeypatch):
    """A fully loaded deployment: all editions, city coordinates, bundle present."""
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle())
    monkeypatch.setattr(report.local_geo, "CITY", StubHandle())
    monkeypatch.setattr(report.local_geo, "ASN", StubHandle())
    monkeypatch.setattr(report.local_geo, "CENTROIDS", StubCentroids())
    monkeypatch.setattr(report.local_anon, "INDEX", StubIndex())


# -- shape -----------------------------------------------------------------


def test_snapshot_reports_ok_when_everything_is_loaded(healthy):
    state = report.snapshot()

    assert state["status"] == "ok"
    assert state["notes"] == []
    assert state["egress"] == "none"
    assert state["geo"]["coordinates"] == "city-db"
    assert state["geo"]["editions"]["country"]["loaded"] is True
    assert state["geo"]["editions"]["country"]["age_days"] == 5
    assert state["anonymiser"]["loaded"] is True
    assert state["anonymiser"]["hosting_asns"] == 906


def test_egress_is_always_reported_as_none(healthy):
    """The first question an air-gap reviewer asks, answered without inference."""
    assert report.snapshot()["egress"] == "none"


def test_coordinate_source_falls_back_to_centroids(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "CITY", StubHandle(loaded=False))

    state = report.snapshot()

    assert state["geo"]["coordinates"] == "country-centroid"
    assert state["geo"]["editions"]["city"]["loaded"] is False
    assert state["geo"]["editions"]["city"]["age_days"] is None


def test_no_coordinate_source_is_reported_and_explained(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "CITY", StubHandle(loaded=False))
    monkeypatch.setattr(report.local_geo, "CENTROIDS", StubCentroids(available=False))

    state = report.snapshot()

    assert state["geo"]["coordinates"] == "none"
    assert state["status"] == "degraded"
    assert any("impossible-travel" in note for note in state["notes"])


# -- degradation -----------------------------------------------------------


def test_missing_country_database_is_degraded_not_ok(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(loaded=False))

    state = report.snapshot()

    assert state["status"] == "degraded"
    assert any("country rules" in note for note in state["notes"])


def test_missing_bundle_is_degraded(monkeypatch, healthy):
    monkeypatch.setattr(report.local_anon, "INDEX", StubIndex(loaded=False))

    state = report.snapshot()

    assert state["status"] == "degraded"
    assert state["anonymiser"]["loaded"] is False
    assert state["anonymiser"]["labels"] == []
    assert any("Tor detection" in note for note in state["notes"])


def test_nothing_loaded_is_unavailable(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(loaded=False))
    monkeypatch.setattr(report.local_geo, "CITY", StubHandle(loaded=False))
    monkeypatch.setattr(report.local_anon, "INDEX", StubIndex(loaded=False))

    assert report.snapshot()["status"] == "unavailable"


def test_stale_data_is_noted(monkeypatch, healthy):
    monkeypatch.setattr(report, "IP_DATA_STALE_WARN_DAYS", 45)
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(age=120))

    state = report.snapshot()

    assert state["status"] == "degraded"
    assert any("older than 45 days" in note for note in state["notes"])


def test_fresh_data_is_not_noted_as_stale(monkeypatch, healthy):
    monkeypatch.setattr(report, "IP_DATA_STALE_WARN_DAYS", 45)
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(age=44))

    assert report.snapshot()["status"] == "ok"


# -- it must never raise ---------------------------------------------------


def test_a_raising_handle_does_not_propagate(monkeypatch, healthy):
    class Exploding:
        path = "/x"

        def reader(self):
            raise RuntimeError("boom")

        def age_days(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(report.local_geo, "COUNTRY", Exploding())

    state = report.snapshot()

    assert state["geo"]["editions"]["country"]["loaded"] is False


def test_a_raising_index_does_not_propagate(monkeypatch, healthy):
    class Exploding:
        def ensure_loaded(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(report.local_anon, "INDEX", Exploding())

    state = report.snapshot()

    assert state["anonymiser"]["loaded"] is False


def test_a_total_failure_degrades_to_unknown(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "_geo", boom)

    state = report.snapshot()

    assert state["status"] == "unknown"
    assert state["egress"] == "none"
    assert state["notes"] == ["snapshot unavailable"]


# -- status_only(): the unauthenticated-safe summary -------------------------
#
# status_only() is what plain /health actually returns; snapshot()'s full detail
# (paths, ages, per-category labels, hosting ASN counts) now requires auth via
# /health/detail. These tests pin exactly one property: the summary word must
# agree with what snapshot() would say, and NOTHING else may be present.


def test_status_only_agrees_with_snapshot_when_everything_is_loaded(healthy):
    assert report.status_only() == {"status": "ok"}
    assert report.status_only()["status"] == report.snapshot()["status"]


def test_status_only_reports_degraded_without_the_reasons(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(loaded=False))

    state = report.status_only()

    assert state == {"status": "degraded"}
    # Confirms this isn't just an empty dict by coincidence -- snapshot() on the
    # same stubbed state really is "degraded" for a documented, specific reason.
    assert report.snapshot()["status"] == "degraded"


def test_status_only_reports_unavailable_without_detail(monkeypatch, healthy):
    monkeypatch.setattr(report.local_geo, "COUNTRY", StubHandle(loaded=False))
    monkeypatch.setattr(report.local_geo, "CITY", StubHandle(loaded=False))
    monkeypatch.setattr(report.local_anon, "INDEX", StubIndex(loaded=False))

    assert report.status_only() == {"status": "unavailable"}


def test_status_only_carries_no_paths_ages_or_labels(monkeypatch, healthy):
    """The exact leak this finding closes: not one field beyond the summary
    word, regardless of what snapshot() itself would additionally reveal."""
    state = report.status_only()

    assert set(state.keys()) == {"status"}
    full = report.snapshot()
    assert "path" not in str(state)
    assert full.get("geo") is not None  # sanity: snapshot() DOES carry it


def test_status_only_a_total_failure_degrades_to_unknown(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "_geo", boom)

    assert report.status_only() == {"status": "unknown"}

"""The MMDB handle: lazy open, hot reload, and degradation.

An authentication decision must never fail on the state of a data file, so every
failure mode here has to end in "return what we have, or None" rather than an
exception. The tests that matter most are the ones covering a database being
replaced or truncated underneath a running engine.
"""

import time

import pytest

from src.utils.info_provider.ip_intel import mmdb as mmdb_module
from src.utils.info_provider.ip_intel.mmdb import MmdbHandle


class FakeReader:
    """Stands in for a maxminddb reader."""

    def __init__(self, records=None, build_epoch=1_700_000_000, raises=False):
        self.records = records or {}
        self._build_epoch = build_epoch
        self.raises = raises
        self.closed = False

    def get(self, ip):
        if self.raises:
            raise ValueError("malformed address")
        return self.records.get(ip)

    def metadata(self):
        class Metadata:
            build_epoch = self._build_epoch

        return Metadata()

    def close(self):
        self.closed = True


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "test.mmdb"
    path.write_bytes(b"placeholder")
    return path


@pytest.fixture
def opener(monkeypatch):
    """Intercept open_database and record how often it is called."""
    state = {"calls": 0, "reader": FakeReader({"1.2.3.4": {"country": "US"}})}

    def open_database(path, mode=None):
        state["calls"] += 1
        if isinstance(state["reader"], Exception):
            raise state["reader"]
        return state["reader"]

    monkeypatch.setattr(mmdb_module.maxminddb, "open_database", open_database)
    return state


# -- no database configured ------------------------------------------------


def test_no_path_is_inert():
    """The city database is optional, and its absence is the shipped default."""
    handle = MmdbHandle(None)

    assert handle.reader() is None
    assert handle.get("1.2.3.4") is None
    assert handle.age_days() is None
    assert handle.build_epoch() is None


def test_missing_file_is_none_not_an_error(tmp_path, opener):
    handle = MmdbHandle(str(tmp_path / "absent.mmdb"), check_interval=0)

    assert handle.reader() is None
    assert handle.get("1.2.3.4") is None
    assert opener["calls"] == 0


# -- loading ---------------------------------------------------------------


def test_database_is_opened_lazily_and_reused(db_file, opener):
    handle = MmdbHandle(str(db_file), check_interval=1000)

    assert opener["calls"] == 0  # nothing opened at construction

    assert handle.get("1.2.3.4") == {"country": "US"}
    assert handle.get("1.2.3.4") == {"country": "US"}
    assert opener["calls"] == 1  # opened once, then reused


def test_opened_in_memory_mode(db_file, monkeypatch):
    """MODE_MEMORY matters: a replaced reader can then be dropped safely.

    With a file-backed mapping, releasing a reader whose file has been replaced
    risks reading from a mapping that no longer describes the file.
    """
    captured = {}

    def open_database(path, mode=None):
        captured["mode"] = mode
        return FakeReader()

    monkeypatch.setattr(mmdb_module.maxminddb, "open_database", open_database)

    MmdbHandle(str(db_file), check_interval=0).reader()

    assert captured["mode"] == mmdb_module.maxminddb.MODE_MEMORY


def test_a_corrupt_database_is_none_rather_than_an_exception(db_file, opener):
    opener["reader"] = Exception("truncated file")
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.reader() is None
    assert handle.get("1.2.3.4") is None


def test_lookup_errors_are_swallowed(db_file, opener):
    """maxminddb raises for a malformed address and on a truncated file."""
    opener["reader"] = FakeReader(raises=True)
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.get("not-an-ip") is None


def test_a_miss_is_none(db_file, opener):
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.get("9.9.9.9") is None


# -- hot reload ------------------------------------------------------------


def test_a_replaced_file_is_picked_up(db_file, opener):
    handle = MmdbHandle(str(db_file), check_interval=0)
    assert handle.get("1.2.3.4") == {"country": "US"}

    # Replace both the file identity and what the opener will return.
    time.sleep(0.01)
    db_file.write_bytes(b"replaced content")
    opener["reader"] = FakeReader({"1.2.3.4": {"country": "DE"}})

    assert handle.get("1.2.3.4") == {"country": "DE"}


def test_an_unchanged_file_is_not_reopened(db_file, opener):
    handle = MmdbHandle(str(db_file), check_interval=0)

    for _ in range(5):
        handle.get("1.2.3.4")

    # stat() runs each time because the interval is zero, but the file identity
    # is unchanged, so the database is opened only once.
    assert opener["calls"] == 1


def test_the_check_is_throttled(db_file, opener):
    handle = MmdbHandle(str(db_file), check_interval=1000)
    handle.reader()

    time.sleep(0.01)
    db_file.write_bytes(b"replaced content")
    opener["reader"] = FakeReader({"1.2.3.4": {"country": "DE"}})

    # Within the interval the change is not looked for.
    assert handle.get("1.2.3.4") == {"country": "US"}
    assert opener["calls"] == 1


def test_a_broken_replacement_keeps_serving_the_loaded_copy(db_file, opener):
    """A half-written file during a copy must not cost us the signal."""
    handle = MmdbHandle(str(db_file), check_interval=0)
    assert handle.get("1.2.3.4") == {"country": "US"}

    time.sleep(0.01)
    db_file.write_bytes(b"half-written")
    opener["reader"] = Exception("truncated file")

    assert handle.get("1.2.3.4") == {"country": "US"}


def test_a_deleted_file_keeps_serving_the_loaded_copy(db_file, opener, caplog):
    handle = MmdbHandle(str(db_file), check_interval=0)
    assert handle.get("1.2.3.4") == {"country": "US"}

    db_file.unlink()

    caplog.set_level("WARNING")
    assert handle.get("1.2.3.4") == {"country": "US"}
    assert "no longer readable" in caplog.text


# -- age reporting ---------------------------------------------------------

def test_age_is_reported_in_whole_days(db_file, opener):
    opener["reader"] = FakeReader(build_epoch=int(time.time()) - 10 * 86400)
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.age_days() == 10


def test_a_future_build_date_is_clamped_to_zero(db_file, opener):
    """A clock problem is reported separately, not as a negative age."""
    opener["reader"] = FakeReader(build_epoch=int(time.time()) + 30 * 86400)
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.age_days() == 0


def test_unreadable_metadata_is_none_not_an_error(db_file, opener):
    class NoMetadata:
        def get(self, ip):
            return None

        def metadata(self):
            raise Exception("unsupported")

    opener["reader"] = NoMetadata()
    handle = MmdbHandle(str(db_file), check_interval=0)

    assert handle.age_days() is None
    assert handle.build_epoch() is None

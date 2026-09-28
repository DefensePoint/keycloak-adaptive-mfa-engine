"""The country centroid table.

This is what supplies coordinates in the shipped country-only configuration, so
its degradation behaviour decides whether impossible-travel and geo-clustering
can contribute at all.
"""

import pytest

from src.utils.info_provider.ip_intel.centroids import CountryCentroids


def write_csv(tmp_path, text, name="centroids.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_loads_rows_and_looks_them_up(tmp_path):
    path = write_csv(
        tmp_path,
        "country_iso,latitude,longitude\nUS,39.7830,-100.4459\nDE,51.1657,10.4515\n",
    )
    centroids = CountryCentroids(path)

    assert centroids.get("US") == (39.7830, -100.4459)
    assert centroids.get("DE") == (51.1657, 10.4515)
    assert centroids.available() is True


def test_header_row_is_skipped_without_needing_to_be_declared(tmp_path):
    """"COUNTRY_ISO" is not two alphabetic characters, so the filter drops it."""
    path = write_csv(tmp_path, "country_iso,latitude,longitude\nUS,1.0,2.0\n")
    centroids = CountryCentroids(path)

    assert len(centroids.table()) == 1
    assert centroids.get("US") == (1.0, 2.0)


def test_a_file_with_no_header_works_too(tmp_path):
    path = write_csv(tmp_path, "US,1.0,2.0\nDE,3.0,4.0\n")

    assert len(CountryCentroids(path).table()) == 2


def test_lookup_is_case_insensitive(tmp_path):
    path = write_csv(tmp_path, "us,1.0,2.0\n")
    centroids = CountryCentroids(path)

    assert centroids.get("US") == (1.0, 2.0)
    assert centroids.get("us") == (1.0, 2.0)


@pytest.mark.parametrize("value", [None, "", "USA", "U"])
def test_unusable_lookup_keys_return_no_coordinate(tmp_path, value):
    path = write_csv(tmp_path, "US,1.0,2.0\n")

    assert CountryCentroids(path).get(value) == (None, None)


def test_unknown_country_returns_no_coordinate(tmp_path):
    path = write_csv(tmp_path, "US,1.0,2.0\n")

    assert CountryCentroids(path).get("ZZ") == (None, None)


def test_malformed_rows_are_skipped(tmp_path):
    path = write_csv(
        tmp_path,
        "\n".join(
            [
                "US,1.0,2.0",
                "TOOSHORT,1.0",  # too few fields
                "DE,north,east",  # non-numeric
                "123,1.0,2.0",  # not alphabetic
                "XYZ,1.0,2.0",  # not two characters
                "",
                "FR,5.0,6.0",
            ]
        ),
    )
    centroids = CountryCentroids(path)

    assert set(centroids.table()) == {"US", "FR"}


def test_missing_file_degrades_to_empty(tmp_path):
    """Expected when running country-only without a generated table."""
    centroids = CountryCentroids(str(tmp_path / "absent.csv"))

    assert centroids.table() == {}
    assert centroids.available() is False
    assert centroids.get("US") == (None, None)


def test_a_directory_in_place_of_the_file_degrades(tmp_path):
    centroids = CountryCentroids(str(tmp_path))

    assert centroids.table() == {}


def test_an_empty_file_warns_and_degrades(tmp_path, caplog):
    path = write_csv(tmp_path, "")

    caplog.set_level("WARNING")
    centroids = CountryCentroids(path)

    assert centroids.table() == {}
    assert "no usable rows" in caplog.text


def test_a_raising_reader_does_not_propagate(tmp_path, monkeypatch, caplog):
    """csv.reader can raise on pathological input, e.g. an over-long field.

    This loads during startup, so an unhandled error would abort the process over
    a malformed data file.
    """
    path = write_csv(tmp_path, "US,1.0,2.0\n")
    centroids = CountryCentroids(path)

    import src.utils.info_provider.ip_intel.centroids as module

    def boom(*args, **kwargs):
        raise Exception("field larger than field limit")

    monkeypatch.setattr(module.csv, "reader", boom)

    caplog.set_level("WARNING")
    assert centroids.table() == {}
    assert "unreadable" in caplog.text


def test_a_nul_byte_does_not_prevent_the_rest_of_the_file_loading(tmp_path):
    """Recorded because the obvious assumption is wrong.

    csv.reader on CPython 3.11 tolerates a NUL rather than raising: it yields a
    junk row, which the ISO filter then drops. The surrounding rows still load.
    """
    path = write_csv(tmp_path, "US,1.0,2.0\nD\x00E,3.0,4.0\nFR,5.0,6.0\n")

    table = CountryCentroids(path).table()

    assert "US" in table
    assert "FR" in table


def test_the_table_is_loaded_once(tmp_path):
    """Load-once is deliberate: the table changes only when the bundle does."""
    path = write_csv(tmp_path, "US,1.0,2.0\n")
    centroids = CountryCentroids(path)

    assert centroids.get("US") == (1.0, 2.0)

    write_csv(tmp_path, "US,9.0,9.0\nDE,3.0,4.0\n")

    assert centroids.get("US") == (1.0, 2.0)
    assert centroids.get("DE") == (None, None)

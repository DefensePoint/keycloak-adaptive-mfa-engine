"""Country centroid coordinates, the fallback when no city database is present.

With no city database configured this becomes the only coordinate source, and
then every address in a country resolves to the same point: intra-country
movement has zero distance and impossible-travel can only observe cross-border
hops.

**Whether to ship a city database is an open decision** (see the note in
``config/environment.py``). The research argument for country-only is that
country data is the most accurate tier of the free databases and is what the
allow/deny lists consume, while a city database adds ~125 MB to the image for
coordinates whose free tier is the weakest. The argument against is that it
degrades two of the nineteen signals. This module supports either.

The table is a data file rather than a Python literal on purpose. It is generated
at bundle-build time from the licensed source, so the coordinates carry the same
provenance and attribution as the rest of the bundle instead of being hardcoded
values of unclear origin.

A missing or malformed file yields an empty table, which means coordinates are
unavailable. That degrades the coordinate-based signals; it never raises.
"""

import csv
import logging
import threading

from src.core.config.environment import COUNTRY_CENTROID_PATH


class CountryCentroids:
    """ISO-3166 alpha-2 to approximate (latitude, longitude).

    Expected CSV format, header optional::

        country_iso,latitude,longitude
        US,39.7830,-100.4459
    """

    def __init__(self, path: str | None = None):
        self._path = path or COUNTRY_CENTROID_PATH
        self._table: dict[str, tuple[float, float]] | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[str, tuple[float, float]]:
        table: dict[str, tuple[float, float]] = {}
        try:
            with open(self._path, newline="", encoding="utf-8") as handle:
                for row in csv.reader(handle):
                    if len(row) < 3:
                        continue
                    iso = row[0].strip().upper()
                    # Also skips the header, since "COUNTRY_ISO" is not 2 alpha.
                    if len(iso) != 2 or not iso.isalpha():
                        continue
                    try:
                        table[iso] = (float(row[1]), float(row[2]))
                    except ValueError:
                        continue
        except OSError as exc:
            # Expected when running country-only without a generated table, so
            # this is informational rather than a warning.
            logging.info(
                "No country centroid table at %s (%s); coordinates will be "
                "unavailable unless a city database is configured.",
                self._path,
                exc,
            )
            return {}
        except Exception as exc:
            # csv.reader can raise on things like an over-long field. This runs
            # during startup, so an unhandled error here would abort the process
            # over a malformed data file.
            logging.warning(
                "Country centroid table %s is unreadable (%s); coordinates will "
                "be unavailable.",
                self._path,
                exc,
            )
            return {}

        if not table:
            logging.warning(
                "Country centroid table %s produced no usable rows.", self._path
            )
        else:
            logging.info("Loaded %s country centroids from %s", len(table), self._path)
        return table

    def table(self) -> dict[str, tuple[float, float]]:
        """The loaded table, read once.

        Deliberately load-once rather than hot-reloaded like the MMDB handles:
        the table is generated with the bundle and changes only when the bundle
        does, at which point the databases beside it are being replaced too.
        """
        if self._table is None:
            with self._lock:
                if self._table is None:
                    self._table = self._load()
        return self._table

    def get(self, country_iso: str | None) -> tuple[float | None, float | None]:
        if not country_iso:
            return (None, None)
        return self.table().get(country_iso.upper(), (None, None))

    def available(self) -> bool:
        return bool(self.table())


CENTROIDS = CountryCentroids()

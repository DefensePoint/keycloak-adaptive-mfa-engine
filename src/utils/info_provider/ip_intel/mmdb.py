"""A reader handle for an MMDB database file.

MMDB is the binary format MaxMind published and open-sourced. The reader library
(``maxminddb``, Apache-2.0) is theirs; the *data* we ship is DB-IP's, under
CC BY 4.0. The same reader handles DB-IP, MaxMind, IPinfo and IP2Location files,
which is what lets an operator substitute their own database by path.

Two design points worth stating, because both are easy to get wrong:

``MODE_MEMORY``, not the default mmap. The file is read into a buffer, so when a
replaced database is loaded the previous reader can simply be dropped and
collected once no lookup still holds it. An mmap-backed reader must never be
closed underneath an in-flight lookup, and there is no cheap way to know when the
last one finishes. The cost is holding the file in RAM, which for the ~17 MB we
ship is a fair trade for not having to reason about that.

The file is re-``stat``'d at most once per ``IP_DATA_RELOAD_CHECK_SECONDS``, so
the syscall stays off the per-lookup path. Hot reload matters because an operator
who drops a fresh database into the volume should not have to restart the engine.

Nothing here raises. A missing, truncated or corrupt file yields ``None`` and the
caller degrades the signal.
"""

import logging
import os
import threading
import time

import maxminddb

from src.core.config.environment import IP_DATA_RELOAD_CHECK_SECONDS


class MmdbHandle:
    def __init__(self, path: str | None, check_interval: float | None = None):
        self._path = path
        self._reader = None
        self._stamp = None
        self._next_check = 0.0
        self._interval = (
            IP_DATA_RELOAD_CHECK_SECONDS if check_interval is None else check_interval
        )
        self._lock = threading.Lock()

    @property
    def path(self) -> str | None:
        """The configured path, for reporting. None when no database is configured."""
        return self._path

    def _stat(self):
        """Identity of the file on disk, or None if it is not readable."""
        if not self._path:
            return None
        try:
            st = os.stat(self._path)
            # Inode included so an atomic replace (write-temp then rename) is
            # detected even if size and mtime happen to match.
            return (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None

    def reader(self):
        """The current reader, or None when no database is available."""
        if not self._path:
            return None

        # The throttle applies whether or not a reader is open. Gating it on
        # `_reader is None` would mean taking the lock and stat()ing on every
        # lookup for as long as the file is absent, which is the common case in a
        # deployment that deliberately ships no city database.
        if time.monotonic() < self._next_check:
            return self._reader

        with self._lock:
            if time.monotonic() < self._next_check:
                return self._reader  # refreshed while this thread waited

            self._next_check = time.monotonic() + self._interval
            stamp = self._stat()

            if stamp is None:
                if self._reader is not None:
                    logging.warning(
                        "IP database %s is no longer readable; serving the "
                        "previously loaded copy until it returns.",
                        self._path,
                    )
                return self._reader

            if stamp == self._stamp and self._reader is not None:
                return self._reader

            try:
                replacement = maxminddb.open_database(self._path, maxminddb.MODE_MEMORY)
            except Exception as exc:
                # A half-written file during a copy lands here. Keep serving the
                # previous copy rather than losing the signal.
                logging.warning("Could not open IP database %s: %s", self._path, exc)
                return self._reader

            self._reader, self._stamp = replacement, stamp
            logging.info(
                "Loaded IP database %s (built %s)",
                self._path,
                self.build_epoch_of(replacement),
            )
            return self._reader

    @staticmethod
    def build_epoch_of(reader) -> int | None:
        try:
            return reader.metadata().build_epoch
        except Exception:
            return None

    def build_epoch(self) -> int | None:
        reader = self.reader()
        return self.build_epoch_of(reader) if reader is not None else None

    def age_days(self) -> int | None:
        """Whole days since the database was built, or None if unavailable.

        Clamped at zero because a negative age is meaningless to a caller comparing
        it against a staleness threshold. Note the clamp also hides its own cause: a
        build date ahead of this host's clock is indistinguishable here from data
        built today. Nothing currently surfaces that, so a skewed clock makes every
        freshness check read as fresh.
        """
        epoch = self.build_epoch()
        if epoch is None:
            return None
        return max(0, int((time.time() - epoch) // 86400))

    def get(self, ip: str):
        """Look up an address. None on miss, bad input, or no database."""
        reader = self.reader()
        if reader is None:
            return None
        try:
            return reader.get(ip)
        except Exception:
            # maxminddb raises ValueError for a malformed address and can raise
            # on a truncated file. Neither may reach the authentication path.
            return None

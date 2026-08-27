"""Cleanup for tests that write to the real database.

These are integration tests: they exercise the repositories against a live
Postgres, which is not reset between runs. Unique identifiers (see
``tests.fixture.util.unique_hash``) are what make them idempotent; this fixture is
what stops them from growing the database by a handful of rows on every run.
"""

import logging

import pytest_asyncio


class Tracker:
    """Records rows to delete once the test finishes."""

    def __init__(self):
        self._rows = []

    def add(self, delete, row):
        """Register ``row`` for deletion by ``delete``, and return it unchanged.

        Returning the row lets a test wrap a create call without restructuring:

            device = tracked.add(DeviceRepository.delete_device, device)
        """
        self._rows.append((delete, row))
        return row

    async def cleanup(self):
        # Reverse order, so rows created later are removed first. Nothing here is
        # allowed to fail the test: cleanup runs after the assertions, and a row
        # the test itself already deleted is an expected state, not an error.
        for delete, row in reversed(self._rows):
            try:
                await delete(row)
            except Exception as exc:
                logging.debug("Could not clean up %r: %s", row, exc)
        self._rows.clear()


@pytest_asyncio.fixture(loop_scope="session")
async def tracked():
    tracker = Tracker()
    try:
        yield tracker
    finally:
        # Runs even when the test fails, so a failing assertion does not leave the
        # row behind to break the next run.
        await tracker.cleanup()

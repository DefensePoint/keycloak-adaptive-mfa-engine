"""Connection defaults so the e2e modules can be collected and run from the host.

Two of the modules here import `src`, which builds `DATABASE_URL` at import time by
formatting the `POSTGRES_*` variables into a template. With none of them set the result
is `postgresql://None:None@None:None/None`, and SQLAlchemy raises while parsing the
port as soon as `src.core.database` is imported:

    ValueError: invalid literal for int() with base 10: 'None'

That happens during collection, so pytest reported "no tests collected, 1 error" and
neither module contributed anything. The failure named a SQLAlchemy internal rather
than the missing configuration, which is why it read as a broken test file.

The values below are the compose stack as seen from the host, which is where a
developer runs pytest. Inside the engine container the same variables are already set
to the container-network equivalents, so nothing here overrides an existing value:
`setdefault` only fills a gap. Point them elsewhere by exporting the real variables.

Note the port. The container reaches Postgres as `postgres:5432`; from the host it is
`localhost:5433`, because that is what the compose file publishes. Using 5432 here is
the mistake to avoid, since on a machine with its own Postgres it would connect to the
wrong database and the failures would look like data problems.
"""

import os

import pytest

# Defaults matching config/keycloak/docker-compose.yml as published to the host.
HOST_DEFAULTS = {
    "POSTGRES_USER": "keycloak",
    "POSTGRES_PASSWORD": "password",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "adaptive_mfa",
    "POSTGRES_SCHEMA": "public",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "",
}

for _name, _value in HOST_DEFAULTS.items():
    os.environ.setdefault(_name, _value)


def pytest_addoption(parser):
    """`--update-baseline` re-records the signal matrix instead of comparing to it.

    A flag rather than an environment variable, and never the default, because
    accepting a change has to be a deliberate act that lands as a reviewable diff. A
    suite that quietly rewrote its own expectations would report every regression as
    a pass.
    """
    parser.addoption(
        "--update-baseline",
        action="store_true",
        default=False,
        help="re-record tests/e2e/baselines/signal-matrix.{json,md} from this run",
    )
    parser.addoption(
        "--headed",
        action="store_true",
        default=False,
        help="run the browser suite with a visible browser, for working out why a "
             "journey failed",
    )


# --- browser tests (opt-in) --------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "browser: drives a real browser via Playwright. Needs `pip install playwright` "
        "and `playwright install chromium`. Deselect with -m 'not browser'.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip the browser suite cleanly when Playwright is not installed.

    An optional dependency should be optional: a machine with only `requests` runs
    everything else and is told why one file did not run, rather than seeing a
    collection error that looks like a broken repository.
    """
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        skip = pytest.mark.skip(
            reason="playwright is not installed; run `pip install playwright` and "
                   "`playwright install chromium` to enable the browser suite"
        )
        for item in items:
            if "browser" in item.keywords:
                item.add_marker(skip)

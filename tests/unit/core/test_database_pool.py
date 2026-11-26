"""The connection pool each engine worker opens.

Every worker holds its own pool, so the engine's share of the database's
connections is WORKERS x (pool size + overflow). On PostgreSQL that share was
fixed at SQLAlchemy's default of 5 + 10, with no way to fit it to a server's
max_connections next to Keycloak's own pool.
"""

import pytest

from src.core import database


@pytest.fixture
def engines(monkeypatch):
    """Record the keyword arguments of the shared (non-health) engine."""
    created = []

    def create_async_engine(url, **kwargs):
        created.append((url, kwargs))
        return object()

    monkeypatch.setattr(database, "create_async_engine", create_async_engine)
    monkeypatch.setattr(database, "async_sessionmaker", lambda **kwargs: object())
    return created


def shared_engine_kwargs(engines):
    # The first engine is the shared pool; the second is the health check's NullPool.
    return engines[0][1]


def test_postgres_pool_is_sized_by_its_settings(engines, monkeypatch):
    monkeypatch.setattr(database, "POSTGRES_POOL_SIZE", 3)
    monkeypatch.setattr(database, "POSTGRES_MAX_OVERFLOW", 4)

    database.DatabaseConnection(url="postgresql://u:p@db:5432/amfa")

    kwargs = shared_engine_kwargs(engines)
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 4


def test_postgres_pool_defaults_keep_the_old_size():
    """5 + 10 is what every deployment ran with before the settings existed."""
    assert (database.POSTGRES_POOL_SIZE, database.POSTGRES_MAX_OVERFLOW) == (5, 10)


@pytest.mark.parametrize(
    "url", ["postgresql://u:p@db:5432/amfa", "mssql+aioodbc://u:p@db/amfa"]
)
def test_pooled_connections_are_checked_before_use(engines, url):
    """After a PostgreSQL restart, each dead pooled connection failed one request with 500."""
    database.DatabaseConnection(url=url)

    assert shared_engine_kwargs(engines)["pool_pre_ping"] is True


def test_sql_server_keeps_its_own_pool_settings(engines, monkeypatch):
    monkeypatch.setattr(database, "POSTGRES_POOL_SIZE", 3)
    monkeypatch.setattr(database, "POSTGRES_MAX_OVERFLOW", 4)
    monkeypatch.setattr(database, "MSSQL_POOL_SIZE", 2)
    monkeypatch.setattr(database, "MSSQL_MAX_OVERFLOW", 1)

    database.DatabaseConnection(url="mssql+aioodbc://u:p@db/amfa")

    kwargs = shared_engine_kwargs(engines)
    assert kwargs["pool_size"] == 2
    assert kwargs["max_overflow"] == 1

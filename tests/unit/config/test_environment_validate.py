import pytest

from src.core.config.environment import validate


def test_validate_raises_when_postgres_env_missing(monkeypatch):
    for name in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OIDC_TRUSTED_BASE_URLS", "https://idp.example.com")

    with pytest.raises(RuntimeError, match="required Postgres env vars are unset"):
        validate()


def test_validate_raises_when_oidc_trusted_base_urls_empty(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "db")
    monkeypatch.setenv("OIDC_TRUSTED_BASE_URLS", "")

    with pytest.raises(RuntimeError, match="OIDC_TRUSTED_BASE_URLS is empty"):
        validate()


def test_validate_passes_when_required_env_is_set(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "db")
    monkeypatch.setenv("OIDC_TRUSTED_BASE_URLS", "https://idp.example.com")

    validate()

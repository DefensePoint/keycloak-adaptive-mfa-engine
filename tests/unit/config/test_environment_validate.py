import pytest

import src.core.config.environment as env
from src.__main__ import main


def test_validate_raises_when_postgres_env_missing(monkeypatch):
    monkeypatch.setattr(env, "POSTGRES_USER", None)
    monkeypatch.setattr(env, "POSTGRES_PASSWORD", "p")
    monkeypatch.setattr(env, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(env, "POSTGRES_PORT", "5432")
    monkeypatch.setattr(env, "DATABASE", "db")
    monkeypatch.setattr(env, "OIDC_TRUSTED_BASE_URLS", ["https://idp.example.com"])

    with pytest.raises(RuntimeError, match="host named 'None'"):
        env.validate()


def test_validate_raises_when_oidc_trusted_base_urls_empty(monkeypatch):
    monkeypatch.setattr(env, "POSTGRES_USER", "u")
    monkeypatch.setattr(env, "POSTGRES_PASSWORD", "p")
    monkeypatch.setattr(env, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(env, "POSTGRES_PORT", "5432")
    monkeypatch.setattr(env, "DATABASE", "db")
    monkeypatch.setattr(env, "OIDC_TRUSTED_BASE_URLS", [])

    with pytest.raises(RuntimeError, match="OIDC_TRUSTED_BASE_URLS is empty"):
        env.validate()


def test_validate_passes_when_required_env_is_set(monkeypatch):
    monkeypatch.setattr(env, "POSTGRES_USER", "u")
    monkeypatch.setattr(env, "POSTGRES_PASSWORD", "p")
    monkeypatch.setattr(env, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(env, "POSTGRES_PORT", "5432")
    monkeypatch.setattr(env, "DATABASE", "db")
    monkeypatch.setattr(env, "OIDC_TRUSTED_BASE_URLS", ["https://idp.example.com"])

    env.validate()


def test_main_calls_validate_before_uvicorn(monkeypatch):
    def boom():
        raise RuntimeError("validate-called")

    def uvicorn_should_not_run(*args, **kwargs):
        raise AssertionError("uvicorn ran before validate")

    monkeypatch.setattr("src.__main__.validate", boom)
    monkeypatch.setattr("src.__main__.uvicorn.run", uvicorn_should_not_run)

    with pytest.raises(RuntimeError, match="validate-called"):
        main()

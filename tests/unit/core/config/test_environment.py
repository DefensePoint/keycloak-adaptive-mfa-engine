import importlib

import pytest

import src.core.config.environment as environment_mod
from src.core.config.environment import _reject_unsafe_fallback_risk_level


def test_more_permissive_fallback_than_default_rejected():
    """FALLBACK_RISK_LEVEL must never be a lower (more
    permissive) risk level than DEFAULT_RISK_LEVEL, the level given to a
    user the engine has never seen before -- an evaluation failure must
    never be treated as SAFER than total unfamiliarity."""
    with pytest.raises(ValueError):
        _reject_unsafe_fallback_risk_level(fallback="1", default="2")


def test_fallback_equal_to_default_accepted():
    _reject_unsafe_fallback_risk_level(fallback="2", default="2")  # must not raise


def test_fallback_stricter_than_default_accepted():
    _reject_unsafe_fallback_risk_level(fallback="3", default="2")  # must not raise


def test_non_numeric_value_raises_rather_than_silently_passing():
    """A non-numeric FALLBACK_RISK_LEVEL/DEFAULT_RISK_LEVEL must still fail
    loudly (ValueError, same as the safety check itself), not be silently
    accepted or crash with some other, less diagnosable exception type."""
    with pytest.raises(ValueError):
        _reject_unsafe_fallback_risk_level(fallback="high", default="2")


def test_shipped_module_level_defaults_are_safe():
    """The actual constants as compiled into the module, not just the
    function in isolation -- proves the check is really wired up against
    the real DEFAULT_RISK_LEVEL/FALLBACK_RISK_LEVEL values, not just
    present as a dead, uncalled function."""
    _reject_unsafe_fallback_risk_level(
        fallback=environment_mod.FALLBACK_RISK_LEVEL,
        default=environment_mod.DEFAULT_RISK_LEVEL,
    )  # must not raise: the shipped code defaults (3, 2) are already safe


def test_module_refuses_to_import_with_an_unsafe_env_combination(monkeypatch):
    """Integration-level check that the module-level call actually runs at
    import time with an unsafe combination sourced from the environment,
    the same way an operator's misconfigured .env would be loaded --
    mirrors the existing RATE_LIMIT_TIME_WINDOW<=0 import-time guard test
    in tests/unit/utils/middleware/test_rate_limit.py."""
    monkeypatch.setenv("FALLBACK_RISK_LEVEL", "1")
    monkeypatch.setenv("DEFAULT_RISK_LEVEL", "2")
    try:
        with pytest.raises(ValueError):
            importlib.reload(environment_mod)
    finally:
        # Restore real config and reload again so every other test in the
        # suite (many of which import constants directly from this module)
        # sees the normal, safe, importable state.
        monkeypatch.undo()
        importlib.reload(environment_mod)


# --- /decision rate limit -------------------------------------------------------


def _reload_with(monkeypatch, **env):
    for key in ("RATE_LIMIT", "RATE_LIMIT_MAX_REQ"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    try:
        importlib.reload(environment_mod)
        return environment_mod.RATE_LIMIT, environment_mod.RATE_LIMIT_MAX_REQ
    finally:
        monkeypatch.undo()
        importlib.reload(environment_mod)


def test_decision_rate_limit_default_leaves_room_for_ordinary_logins(monkeypatch):
    """At 4 per minute the fifth quick login by one user got a 429, which the
    Keycloak plugin treats like an outage: the login continued at the realm's
    fallback risk level, without a step-up when that level is 1."""
    assert _reload_with(monkeypatch) == (True, 30)


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off", " false "])
def test_rate_limit_can_be_switched_off(monkeypatch, value):
    # bool("False") is True: the switch could not be turned off.
    assert _reload_with(monkeypatch, RATE_LIMIT=value)[0] is False


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", ""])
def test_rate_limit_stays_on(monkeypatch, value):
    assert _reload_with(monkeypatch, RATE_LIMIT=value)[0] is True


def test_a_rate_limit_typo_stops_the_engine(monkeypatch):
    """A typo must not quietly turn the protection off."""
    monkeypatch.setenv("RATE_LIMIT", "flase")
    try:
        with pytest.raises(ValueError, match="RATE_LIMIT"):
            importlib.reload(environment_mod)
    finally:
        monkeypatch.undo()
        importlib.reload(environment_mod)

"""Tests for DecisionService.__param_is_enabled — the shared signal on/off gate.

Root-cause fix (global): the helper used to read an ``"enabled"`` key that is
never written to a param config (configs carry ``"disabled"``), so it returned
``True`` for every param, including params that are absent from
``decision_params`` entirely. Disabled signals are stripped from
``decision_params`` upstream, so the correct meaning of "enabled" is: present in
``decision_params`` and not explicitly disabled.

Fixing the helper corrects every call site at once: the account-action (E4)
gate, the short-term change-detection filter, and the whitelist/blacklist paths.
It also fixes the !16 regression where ``recent_account_change`` ran even though
it ships disabled by default.

These drive the helper directly, no Redis/DB/network.
"""

from src.service.decision import DecisionService


def _svc(decision_params: dict) -> DecisionService:
    # Bypass __init__ (which builds a Redis client); the helper needs only
    # decision_params.
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = decision_params
    return svc


def _is_enabled(svc: DecisionService, name: str) -> bool:
    return svc._DecisionService__param_is_enabled(name)


def test_absent_param_is_not_enabled():
    # A signal that is off is stripped from decision_params, so it is absent.
    svc = _svc({"impossible_travel": {"weight": 3}})
    assert _is_enabled(svc, "recent_account_change") is False


def test_present_param_is_enabled():
    svc = _svc({"recent_account_change": {"weight": 3}})
    assert _is_enabled(svc, "recent_account_change") is True


def test_present_but_explicitly_disabled_is_not_enabled():
    # Robustness: even if a disabled entry survives into decision_params, it must
    # read as off.
    svc = _svc({"recent_account_change": {"weight": 3, "disabled": True}})
    assert _is_enabled(svc, "recent_account_change") is False


def test_recent_account_change_off_by_default_regression():
    # !16 regression: with no per-realm opt-in the signal must read as off, so it
    # never runs in its shipped default state.
    svc = _svc({"__meta": {"id": "x", "scoring_config": None}})
    assert _is_enabled(svc, "recent_account_change") is False

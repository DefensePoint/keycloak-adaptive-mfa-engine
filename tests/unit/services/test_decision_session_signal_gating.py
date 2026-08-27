"""Option B: login_failure and concurrent_session are gated by decision_params.

These two behavioural signals used to be gated only by their deployment-level
env toggle, so they were computed (and, via the change filter, contributed to
risk) even when the signal was disabled for the realm. Every other signal is
gated by per-realm ``decision_params`` enablement, so this made them the odd
ones out and let them run while disabled.

Option B aligns them with the majority: they run only when the deployment
toggle is on AND the signal is enabled in ``decision_params`` (the E4 pattern).
Their shipped default stays disabled, consistent with the project's opt-in
philosophy.

Driven directly, no Redis/DB/network: empty process lists make the underlying
checks return "NORMAL", so these assert only whether the signal is evaluated at
all (key present) based on gating.
"""

from src.service import decision
from src.service.decision import DecisionService


def _svc(decision_params: dict) -> DecisionService:
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = decision_params
    return svc


def _evaluate(svc: DecisionService) -> dict:
    risk_eval_vars: dict = {}
    svc._DecisionService__evaluate_session_failure_signals(
        risk_eval_vars,
        valid_processes=[],
        invalid_processes=[],
        current_event={"event_time": 1_700_000_000_000},
    )
    return risk_eval_vars


def test_login_failure_not_evaluated_when_param_absent(monkeypatch):
    monkeypatch.setattr(decision, "LOGIN_FAILURE_DETECTION_ENABLED", True)
    monkeypatch.setattr(decision, "CONCURRENT_SESSION_DETECTION_ENABLED", True)
    rev = _evaluate(_svc({"impossible_travel": {"weight": 3}}))
    assert "login_failure" not in rev


def test_login_failure_evaluated_when_param_present(monkeypatch):
    monkeypatch.setattr(decision, "LOGIN_FAILURE_DETECTION_ENABLED", True)
    monkeypatch.setattr(decision, "CONCURRENT_SESSION_DETECTION_ENABLED", False)
    rev = _evaluate(_svc({"login_failure": {"weight": 3}}))
    assert rev.get("login_failure") == "NORMAL"


def test_concurrent_session_not_evaluated_when_param_absent(monkeypatch):
    monkeypatch.setattr(decision, "LOGIN_FAILURE_DETECTION_ENABLED", True)
    monkeypatch.setattr(decision, "CONCURRENT_SESSION_DETECTION_ENABLED", True)
    rev = _evaluate(_svc({"impossible_travel": {"weight": 3}}))
    assert "concurrent_session" not in rev


def test_concurrent_session_evaluated_when_param_present(monkeypatch):
    monkeypatch.setattr(decision, "LOGIN_FAILURE_DETECTION_ENABLED", False)
    monkeypatch.setattr(decision, "CONCURRENT_SESSION_DETECTION_ENABLED", True)
    rev = _evaluate(_svc({"concurrent_session": {"weight": 3}}))
    assert rev.get("concurrent_session") == "NORMAL"


def test_env_toggle_off_skips_even_when_param_present(monkeypatch):
    # The deployment kill-switch still wins.
    monkeypatch.setattr(decision, "LOGIN_FAILURE_DETECTION_ENABLED", False)
    monkeypatch.setattr(decision, "CONCURRENT_SESSION_DETECTION_ENABLED", False)
    rev = _evaluate(
        _svc({"login_failure": {"weight": 3}, "concurrent_session": {"weight": 3}})
    )
    assert "login_failure" not in rev
    assert "concurrent_session" not in rev

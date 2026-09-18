"""Unit tests for the A4 configurable hazard thresholds in ``__hazard_activation``.

Two magic numbers in the weight-mode hazard gate are now env-configurable:

- ``HAZARD_CHANGED_PARAMS_THRESHOLD`` (default 6): how many signals must change
  at once to force Risk 3;
- ``HAZARD_FAILED_ATTEMPTS_THRESHOLD`` (default 2): how many failed logins in the
  last 24h push that Risk 3 to Risk 4, and gate the consecutive-high-risk
  escalation.

These drive ``__hazard_activation`` directly. The only I/O it needs
(``__count_failed_attempts_in_last_24h``) is stubbed per test, so no Redis/DB is
touched.
"""

import pytest

from src.service import decision
from src.service.decision import DecisionService


def _svc(decision_params: dict, failed_24h: int) -> DecisionService:
    svc = DecisionService.__new__(DecisionService)
    svc.risk_levels = [1, 2, 3, 4]
    svc.decision_params = decision_params
    svc.len_valid_auths = 100  # comfortably above MIN_AUTH_EVENTS + 2

    async def _fake_failed_count():
        return failed_24h

    # Shadow the name-mangled Redis-backed counter with a static stub.
    svc._DecisionService__count_failed_attempts_in_last_24h = _fake_failed_count
    return svc


async def _hazard(svc, changed_vars, *, last=0, second_last=0):
    rev = {"last_decision": last, "second_last_decision": second_last}
    return await svc._DecisionService__hazard_activation(rev, changed_vars)


# --- changed-params threshold ----------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_changed_params_gate_forces_risk_3(monkeypatch):
    # Lower the gate to 3 and feed 3 weight-1 changes. The partial path alone
    # would score cumulative weight 3 -> Risk 2; the gate overrides to Risk 3,
    # which proves the gate (not the partial path) produced the result.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 3)
    svc = _svc({"a": {"weight": 1}, "b": {"weight": 1}, "c": {"weight": 1}}, failed_24h=0)
    assert await _hazard(svc, ["a", "b", "c"]) == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_below_changed_params_gate_uses_partial_path(monkeypatch):
    # Default gate of 6; only 3 low-weight changes -> gate does not fire and the
    # cumulative-weight partial path (weight 3 -> Risk 2) is used instead.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 6)
    svc = _svc({"a": {"weight": 1}, "b": {"weight": 1}, "c": {"weight": 1}}, failed_24h=0)
    assert await _hazard(svc, ["a", "b", "c"]) == 2


# --- failed-attempts threshold ---------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_gate_escalates_to_4_when_failures_meet_threshold(monkeypatch):
    # Gate fires and failures (2) meet the default threshold (2) -> Risk 4.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 3)
    monkeypatch.setattr(decision, "HAZARD_FAILED_ATTEMPTS_THRESHOLD", 2)
    svc = _svc({"a": {"weight": 1}, "b": {"weight": 1}, "c": {"weight": 1}}, failed_24h=2)
    assert await _hazard(svc, ["a", "b", "c"]) == 4


@pytest.mark.asyncio(loop_scope="session")
async def test_gate_failures_below_threshold_stays_risk_3(monkeypatch):
    # Same gate, but failures (1) below the threshold (2) -> stays Risk 3.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 3)
    monkeypatch.setattr(decision, "HAZARD_FAILED_ATTEMPTS_THRESHOLD", 2)
    svc = _svc({"a": {"weight": 1}, "b": {"weight": 1}, "c": {"weight": 1}}, failed_24h=1)
    assert await _hazard(svc, ["a", "b", "c"]) == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_attempts_threshold_is_configurable(monkeypatch):
    # Tightening the failed-attempts threshold to 1 makes a single failure enough
    # to push the gate's Risk 3 up to Risk 4.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 3)
    monkeypatch.setattr(decision, "HAZARD_FAILED_ATTEMPTS_THRESHOLD", 1)
    svc = _svc({"a": {"weight": 1}, "b": {"weight": 1}, "c": {"weight": 1}}, failed_24h=1)
    assert await _hazard(svc, ["a", "b", "c"]) == 4


# --- consecutive-escalation call site --------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_consecutive_escalation_uses_failed_attempts_threshold(monkeypatch):
    # Below the changed-params gate (2 changes < 6), the partial path scores
    # cumulative weight 6 -> Risk 3. With two prior high-risk logins and failures
    # meeting the threshold, that 3 escalates to 4.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 6)
    monkeypatch.setattr(decision, "HAZARD_FAILED_ATTEMPTS_THRESHOLD", 2)
    svc = _svc({"a": {"weight": 3}, "b": {"weight": 3}}, failed_24h=2)
    assert await _hazard(svc, ["a", "b"], last=3, second_last=3) == 4


@pytest.mark.asyncio(loop_scope="session")
async def test_consecutive_escalation_skipped_below_failed_threshold(monkeypatch):
    # Same setup but failures (1) below the threshold (2) -> no escalation, the
    # partial-path Risk 3 stands.
    monkeypatch.setattr(decision, "HAZARD_CHANGED_PARAMS_THRESHOLD", 6)
    monkeypatch.setattr(decision, "HAZARD_FAILED_ATTEMPTS_THRESHOLD", 2)
    svc = _svc({"a": {"weight": 3}, "b": {"weight": 3}}, failed_24h=1)
    assert await _hazard(svc, ["a", "b"], last=3, second_last=3) == 3

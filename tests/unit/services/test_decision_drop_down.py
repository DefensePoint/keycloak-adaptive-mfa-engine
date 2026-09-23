import pytest

from src.service import decision
from src.service.decision import DecisionService

_NOW = 1_700_000_000_000  # fixed epoch ms (no wall-clock needed)
_DAY = 86_400_000


def _svc():
    # __drop_down uses only risk_eval_vars + module constants, so bypass
    # __init__ (which builds a Redis client) with __new__.
    return DecisionService.__new__(DecisionService)


def _rev(last, gap_days):
    return {
        "last_decision": last,
        "previous_event": {"event_time": _NOW},
        "current_event": {"event_time": _NOW + int(gap_days * _DAY)},
    }


def _drop(svc, rev):
    return svc._DecisionService__drop_down(rev)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    # Pin config so tests don't depend on the ambient environment.
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_DAYS", 30)
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_STEPS", 2)


def test_recent_escalation_drops_one_step():
    svc = _svc()
    assert _drop(svc, _rev(last=4, gap_days=2)) == 3
    assert _drop(svc, _rev(last=3, gap_days=2)) == 2


def test_stale_escalation_drops_two_steps():
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=45)) == 1
    assert _drop(svc, _rev(last=4, gap_days=45)) == 2


def test_stale_drop_is_clamped_to_risk_1(monkeypatch):
    # last - steps == 0 without the clamp (3 - 3); must be forced back up to 1.
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_STEPS", 3)
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=45)) == 1

    # last - steps == -1 without the clamp (4 - 5); still must clamp to 1.
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_STEPS", 5)
    assert _drop(svc, _rev(last=4, gap_days=45)) == 1


def test_threshold_boundary_is_baseline():
    # Gap exactly == threshold is NOT stale (strict greater-than).
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=30)) == 2


def test_missing_event_time_falls_back_to_baseline():
    svc = _svc()
    rev = {"last_decision": 3, "previous_event": {}, "current_event": {}}
    assert _drop(svc, rev) == 2


def test_negative_gap_falls_back_to_baseline():
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=-5)) == 2


def test_shorter_configured_window_makes_gap_stale(monkeypatch):
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_DAYS", 7)
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=10)) == 1


def test_non_numeric_event_time_falls_back_to_baseline():
    svc = _svc()
    rev = {
        "last_decision": 3,
        "previous_event": {"event_time": 1_700_000_000_000},
        "current_event": {"event_time": "abc"},
    }
    assert _drop(svc, rev) == 2


def test_zero_configured_steps_still_drops_at_least_one_step(monkeypatch):
    # Guards against a misconfigured DROP_DOWN_DECAY_STEPS<=0: a stale gap must
    # still relax by at least the baseline one step, never zero steps.
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_STEPS", 0)
    svc = _svc()
    assert _drop(svc, _rev(last=3, gap_days=45)) == 2

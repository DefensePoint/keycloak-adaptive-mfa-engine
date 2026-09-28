"""Integration tests for the B6 time-decay fix.

Unlike ``test_decision_drop_down.py`` (which drives
``DecisionService.__drop_down`` in isolation with a hand-built
``risk_eval_vars`` dict), these tests prove the REAL pipeline drives the
decay:

- Test A: the real ``EvalRisk.process()`` carries the two event dicts'
  ``event_time`` into ``risk_eval_vars`` untouched, and feeding that real
  output into the real ``__drop_down`` produces the decayed ACR.
- Test B: the real ``__evaluate_risk`` routes a clean login (no changed
  vars, no blacklist) to ``__drop_down`` via the weight-scoring path, and
  the post-drop_down credibility adjustment is a genuine no-op so the
  decayed value survives to the final decision.

No live Redis/DB/network is used anywhere: the decision-logic entry points
that need I/O for a clean login (concurrent-session/login-failure checks,
`__count_failed_attempts_in_last_24h`) are simply not on this code path, so
nothing about the decision logic itself is faked.
"""

import pytest

from src.service import decision
from src.service.decision import DecisionService
from src.service.risk_evaluation import EvalRisk

import pandas as pd

_DAY = 86_400_000  # ms per day
_BASE = 1_700_000_000_000  # fixed epoch ms (no wall clock)


@pytest.fixture(autouse=True)
def _pin_decay_config(monkeypatch):
    # Pin config so tests don't depend on the ambient environment.
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_DAYS", 30)
    monkeypatch.setattr(decision, "DROP_DOWN_DECAY_STEPS", 2)


def _svc():
    # DecisionService.__init__ builds a Redis client; bypass it with
    # __new__ since none of the code paths exercised here touch Redis.
    return DecisionService.__new__(DecisionService)


# ---------------------------------------------------------------------------
# Test A: real EvalRisk preserves event_time; real __drop_down decays on it.
# ---------------------------------------------------------------------------


def test_eval_risk_seam_preserved_and_drop_down_decays_on_stale_gap():
    df_user = pd.DataFrame([{"event_time": _BASE}])

    previous_event_dict = {"event_time": _BASE}
    current_event_dict = {"event_time": _BASE + 45 * _DAY}  # 45-day stale gap

    rev = EvalRisk(
        df_user=df_user,
        last_decision=3,
        second_last_decision=3,
        previous_event_dict=previous_event_dict,
        current_event_dict=current_event_dict,
        enabled_params=[],  # no flag branches run; df_user is never inspected
    ).process()

    # The seam: EvalRisk.process() must carry the raw event dicts through
    # unchanged into risk_eval_vars.
    assert rev["previous_event"]["event_time"] == _BASE
    assert rev["current_event"]["event_time"] == _BASE + 45 * _DAY
    assert rev["last_decision"] == 3

    svc = _svc()
    # Stale gap (45 days > 30-day DROP_DOWN_DECAY_DAYS): decay by
    # DROP_DOWN_DECAY_STEPS=2 => 3 - 2 = 1.
    assert svc._DecisionService__drop_down(rev) == 1


def test_eval_risk_seam_preserved_and_drop_down_baseline_on_recent_gap():
    df_user = pd.DataFrame([{"event_time": _BASE}])

    previous_event_dict = {"event_time": _BASE}
    current_event_dict = {"event_time": _BASE + 2 * _DAY}  # 2-day recent gap

    rev = EvalRisk(
        df_user=df_user,
        last_decision=3,
        second_last_decision=3,
        previous_event_dict=previous_event_dict,
        current_event_dict=current_event_dict,
        enabled_params=[],
    ).process()

    assert rev["previous_event"]["event_time"] == _BASE
    assert rev["current_event"]["event_time"] == _BASE + 2 * _DAY
    assert rev["last_decision"] == 3

    svc = _svc()
    # Recent gap (2 days, not stale): baseline one-step drop => 3 - 1 = 2.
    # Same pipeline as the stale case above; only the timestamp gap differs,
    # proving the decay is driven purely by event_time, not by rebuilding the
    # rev dict differently.
    assert svc._DecisionService__drop_down(rev) == 2


# ---------------------------------------------------------------------------
# Test B: real __evaluate_risk routes a clean login to __drop_down, and the
# credibility adjustment is a genuine no-op so the decayed ACR survives.
# ---------------------------------------------------------------------------


def _build_rev(gap_days: float) -> dict:
    """Build risk_eval_vars via the REAL EvalRisk pipeline for a clean login.

    previous_event/current_event are identical on every request variable
    tracked by decision_params below (ip_address, device_id), so
    __detect_param_change_short_term yields no diff-based changes. With
    enabled_params=[], every behavioural flag takes EvalRisk's benign
    default (POSSIBLE/NOT ANONYMOUS/LOW/ACCEPTABLE/ACTIVE/TREND/TREND),
    none of which are the triggering values
    (IMPOSSIBLE/ANONYMOUS/HIGH/FORBIDDEN/INACTIVE/ANOMALOUS) that
    __detect_param_change_short_term checks for, so changed_vars == [].
    """
    df_user = pd.DataFrame([{"event_time": _BASE}])

    previous_event_dict = {
        "event_time": _BASE,
        "ip_address": "1.2.3.4",
        "device_id": "dev-1",
    }
    current_event_dict = {
        "event_time": _BASE + int(gap_days * _DAY),
        "ip_address": "1.2.3.4",
        "device_id": "dev-1",
    }

    return EvalRisk(
        df_user=df_user,
        last_decision=3,
        second_last_decision=3,
        previous_event_dict=previous_event_dict,
        current_event_dict=current_event_dict,
        enabled_params=[],
    ).process()


def _build_svc() -> DecisionService:
    svc = _svc()
    svc.risk_levels = [1, 2, 3, 4]
    # Minimal enabled param set: the two request variables that are held
    # identical between previous_event/current_event in _build_rev, so
    # __detect_param_change_short_term's diff-based check contributes
    # nothing to changed_vars.
    svc.decision_params = {
        "ip_address": {"enabled": True, "weight": 3},
        "device_id": {"enabled": True, "weight": 3},
    }
    # Read by __hazard_activation only; not on the clean-login/drop_down
    # path exercised here, but set defensively since __evaluate_risk's
    # contract allows reaching it.
    svc.len_valid_auths = 10
    return svc


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluate_risk_clean_login_routes_to_drop_down_stale(monkeypatch):
    # Force the weight-scoring path (the repo's env default is "bayesian";
    # pin "weight" explicitly so the test exercises the drop_down path
    # regardless of the ambient environment).
    monkeypatch.setattr(decision, "SCORING_MODE", "weight")

    svc = _build_svc()
    rev = _build_rev(gap_days=45)  # stale gap

    # Credibility 0.5/0.5 => c = 0.5*0.55 + 0.5*0.45 = 0.5, which falls in
    # __adjust_for_credibility's "elif c < 0.6" (medium-risk) band: that
    # branch only logs and returns `decision` unchanged. This is the genuine
    # no-op band, confirmed by reading the code rather than assumed --
    # 1.0/1.0 is NOT a no-op here (see __adjust_for_credibility itself for
    # why: the "very familiar" band actively lowers the decision).
    result = await svc._DecisionService__evaluate_risk(rev, 0.5, 0.5, [], [])

    # Real path: no changed vars/blacklist -> __drop_down -> stale 45-day
    # gap decays by DROP_DOWN_DECAY_STEPS=2 -> 3 - 2 = 1. Credibility and
    # whitelist/blacklist adjustments are no-ops, so 1 survives to the
    # final decision.
    assert result == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluate_risk_clean_login_routes_to_drop_down_recent(monkeypatch):
    monkeypatch.setattr(decision, "SCORING_MODE", "weight")

    svc = _build_svc()
    rev = _build_rev(gap_days=2)  # recent gap; only the timestamp changes

    result = await svc._DecisionService__evaluate_risk(rev, 0.5, 0.5, [], [])

    # Same pipeline as the stale variant above; only the event_time gap
    # differs. Baseline one-step drop -> 3 - 1 = 2, and it survives the
    # (no-op) credibility/whitelist/blacklist adjustments unchanged.
    assert result == 2

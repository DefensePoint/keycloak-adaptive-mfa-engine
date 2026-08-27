"""Integration tests for the B4 hourly-login-histogram fix.

Unlike ``tests/unit/services/risk_evaluation/checks/test_datetime_data.py``
(which calls ``process_datetime_data`` directly), these tests prove the fix
(``bins=24, range=(0, 24)`` in
``src/service/risk_evaluation/checks/datetime_data.py``) is actually
exercised through the REAL pipeline:

- Test A: the real ``EvalRisk.process()`` (with only ``date_time`` enabled)
  calls the real ``process_datetime_data`` and produces ``date_time="HIGH"``
  for a rare-hour login and ``date_time="LOW"`` for the user's dominant hour.
- Test B: the real ``DecisionService.__detect_param_change_short_term``
  (private method, accessed via name-mangling) lifts a real ``date_time ==
  "HIGH"`` risk_eval_vars into ``changed_vars``, and does NOT do so for the
  real ``LOW`` result.

No live Redis/DB/network is used anywhere. ``__detect_param_change_short_term``
only reads ``self.decision_params`` and the ``risk_eval_vars`` dict passed to
it (see ``src/service/decision.py`` ~lines 613-682); it performs no I/O, so
``DecisionService`` is built via ``__new__`` (bypassing ``__init__``'s Redis
client) with just that one plain attribute set. Nothing about ``EvalRisk``,
``process_datetime_data``, or ``__detect_param_change_short_term`` is mocked,
monkeypatched, or reimplemented.
"""

import datetime

import pandas as pd

from src.service.decision import DecisionService
from src.service.risk_evaluation import EvalRisk


def _ts(year: int, month: int, day: int, hour: int) -> float:
    """Build an epoch-ms timestamp (local time, no wall clock) for a weekday login."""
    return datetime.datetime(year, month, day, hour, 0, 0).timestamp() * 1000


# History: 10 weekday logins at hour 23 (this user's dominant/common hour),
# one weekday login at hour 03, and one weekday login at hour 22 (so hour 22
# has only 1 prior login, i.e. <= 3, and the histogram branch is entered for
# it). All dates are Mon-Fri: 2025-01-06..10 and 2025-01-13..17 (Mon-Fri),
# plus 2025-01-20 (Mon) and 2025-01-21 (Tue).
_HISTORY_ROWS = [
    {"event_time": _ts(2025, 1, 6, 23), "lat": 0.0, "long": 0.0},  # Mon
    {"event_time": _ts(2025, 1, 7, 23), "lat": 0.0, "long": 0.0},  # Tue
    {"event_time": _ts(2025, 1, 8, 23), "lat": 0.0, "long": 0.0},  # Wed
    {"event_time": _ts(2025, 1, 9, 23), "lat": 0.0, "long": 0.0},  # Thu
    {"event_time": _ts(2025, 1, 10, 23), "lat": 0.0, "long": 0.0},  # Fri
    {"event_time": _ts(2025, 1, 13, 23), "lat": 0.0, "long": 0.0},  # Mon
    {"event_time": _ts(2025, 1, 14, 23), "lat": 0.0, "long": 0.0},  # Tue
    {"event_time": _ts(2025, 1, 15, 23), "lat": 0.0, "long": 0.0},  # Wed
    {"event_time": _ts(2025, 1, 16, 23), "lat": 0.0, "long": 0.0},  # Thu
    {"event_time": _ts(2025, 1, 17, 23), "lat": 0.0, "long": 0.0},  # Fri
    {"event_time": _ts(2025, 1, 20, 3), "lat": 0.0, "long": 0.0},  # Mon
    {"event_time": _ts(2025, 1, 21, 22), "lat": 0.0, "long": 0.0},  # Tue
]

_PREVIOUS_EVENT_DICT = dict(_HISTORY_ROWS[0])  # "any" history row, per the brief

# Current event: a weekday login (2025-01-22 is a Wednesday) at hour 22 --
# rare for this user (only 1 prior login at hour 22).
_CURRENT_EVENT_HIGH = {"event_time": _ts(2025, 1, 22, 22)}

# Contrast current event: same weekday, but at hour 23 -- the user's
# dominant hour (10 prior logins), so the early-return
# `n_logins_current_hour > 3` path yields LOW without even reaching the
# (fixed) histogram.
_CURRENT_EVENT_LOW = {"event_time": _ts(2025, 1, 22, 23)}


def _history_df() -> pd.DataFrame:
    # Fresh copy per EvalRisk() call: process_datetime_data mutates df_user
    # in place (adds date_time/hour/week_day/day_type columns), and each
    # call must see the untouched history.
    return pd.DataFrame(_HISTORY_ROWS)


# ---------------------------------------------------------------------------
# Test A: the real EvalRisk.process() runs the real (fixed) histogram.
# ---------------------------------------------------------------------------


def test_eval_risk_scores_rare_hour_high_through_fixed_histogram():
    rev = EvalRisk(
        df_user=_history_df(),
        last_decision=2,
        second_last_decision=2,
        previous_event_dict=_PREVIOUS_EVENT_DICT,
        current_event_dict=_CURRENT_EVENT_HIGH,
        enabled_params=["date_time"],
    ).process()

    # With the pre-B4 bins=23, range=(0, 23) histogram, hours 22 and 23 were
    # conflated into the same last bin, so this rare 22:00 login was wrongly
    # scored as if it shared hour 23's high frequency -> LOW. The fixed
    # bins=24, range=(0, 24) histogram gives hour 22 its own bin -> HIGH.
    assert rev["date_time"] == "HIGH"


def test_eval_risk_scores_dominant_hour_low_via_early_return():
    rev = EvalRisk(
        df_user=_history_df(),
        last_decision=2,
        second_last_decision=2,
        previous_event_dict=_PREVIOUS_EVENT_DICT,
        current_event_dict=_CURRENT_EVENT_LOW,
        enabled_params=["date_time"],
    ).process()

    # 10 prior logins at hour 23 (> 3) -> early-return path, no histogram
    # involved at all.
    assert rev["date_time"] == "LOW"


# ---------------------------------------------------------------------------
# Test B: the real __detect_param_change_short_term lifts date_time=HIGH
# (produced by the real, fixed histogram) into changed_vars.
# ---------------------------------------------------------------------------


def _svc() -> DecisionService:
    # DecisionService.__init__ builds a Redis client; __detect_param_change_
    # short_term only reads self.decision_params (see src/service/decision.py
    # ~lines 613-682), so bypass __init__ via __new__ and set just that one
    # plain attribute.
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = {"date_time": {"enabled": True, "weight": 2}}
    return svc


def test_detect_param_change_short_term_flags_high_date_time():
    rev_high = EvalRisk(
        df_user=_history_df(),
        last_decision=2,
        second_last_decision=2,
        previous_event_dict=_PREVIOUS_EVENT_DICT,
        current_event_dict=_CURRENT_EVENT_HIGH,
        enabled_params=["date_time"],
    ).process()
    assert rev_high["date_time"] == "HIGH"  # sanity: same seam as Test A

    svc = _svc()
    changed = svc._DecisionService__detect_param_change_short_term(rev_high)

    assert "date_time" in changed


def test_detect_param_change_short_term_ignores_low_date_time():
    rev_low = EvalRisk(
        df_user=_history_df(),
        last_decision=2,
        second_last_decision=2,
        previous_event_dict=_PREVIOUS_EVENT_DICT,
        current_event_dict=_CURRENT_EVENT_LOW,
        enabled_params=["date_time"],
    ).process()
    assert rev_low["date_time"] == "LOW"  # sanity: same seam as Test A

    svc = _svc()
    changed = svc._DecisionService__detect_param_change_short_term(rev_low)

    assert "date_time" not in changed

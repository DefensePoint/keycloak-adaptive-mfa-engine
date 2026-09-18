"""Unit tests for the A3 weighted-aggregation fix in ``__partial_decisions``.

The legacy aggregation was ``ceil(sum(per-param risk) / count)``, which had two
defects this fix removes:

- count-insensitive: one weight-3 change and five weight-3 changes both scored 3;
- non-monotonic (dilution): adding a low-weight change lowered the average, so
  more evidence produced a *lower* risk.

The new logic sums each changed parameter's configured ``weight`` and buckets
that cumulative weight by ``WEIGHT_RISK_BANDS`` (default ``(3, 6)``):

    weight < 3      -> Risk 1
    3 <= weight < 6 -> Risk 2
    weight >= 6     -> Risk 3

These tests drive ``__partial_decisions`` directly (no Redis/DB/network).
"""

import pytest

from src.service import decision
from src.service.decision import DecisionService


def _svc(decision_params: dict) -> DecisionService:
    # Bypass __init__ (which builds a Redis client); this path touches none of it.
    svc = DecisionService.__new__(DecisionService)
    svc.risk_levels = [1, 2, 3, 4]
    svc.decision_params = decision_params
    return svc


def _score(svc: DecisionService, changed_vars):
    return svc._DecisionService__partial_decisions(changed_vars)


# --- band boundaries --------------------------------------------------------


def test_no_changes_is_risk_1():
    svc = _svc({"a": {"weight": 3}})
    assert _score(svc, []) == 1


def test_single_weight_1_change_is_risk_1():
    # Cumulative weight 1 < 3 -> Risk 1.
    svc = _svc({"a": {"weight": 1}})
    assert _score(svc, ["a"]) == 1


def test_single_weight_2_change_is_risk_1():
    # Cumulative weight 2 < 3 -> Risk 1 (a single low-weight anomaly is minor).
    svc = _svc({"a": {"weight": 2}})
    assert _score(svc, ["a"]) == 1


def test_single_weight_3_change_is_risk_2():
    # Cumulative weight 3 -> Risk 2. (Legacy code scored this a 3; A3 makes a
    # lone high-weight anomaly less alarming than several stacked together.)
    svc = _svc({"a": {"weight": 3}})
    assert _score(svc, ["a"]) == 2


def test_two_weight_3_changes_is_risk_3():
    # Cumulative weight 6 -> Risk 3.
    svc = _svc({"a": {"weight": 3}, "b": {"weight": 3}})
    assert _score(svc, ["a", "b"]) == 3


# --- the two defects A3 removes --------------------------------------------


def test_count_sensitivity_one_vs_two_changes_differ():
    # Legacy ceil-average gave both cases Risk 3; the cumulative sum separates
    # them: one weight-3 change (3) is Risk 2, two (6) is Risk 3.
    svc = _svc({"a": {"weight": 3}, "b": {"weight": 3}})
    assert _score(svc, ["a"]) == 2
    assert _score(svc, ["a", "b"]) == 3


def test_low_weight_change_never_dilutes_a_high_weight_one():
    # Legacy: [3,1,1,1] -> ceil(6/4) = 2, i.e. extra low-weight evidence pulled
    # a weight-3 change DOWN. New: 3+1+1+1 = 6 -> Risk 3, never below the
    # weight-3-only case (Risk 2). More evidence can only raise risk.
    svc = _svc(
        {"a": {"weight": 3}, "b": {"weight": 1}, "c": {"weight": 1}, "d": {"weight": 1}}
    )
    high_only = _score(svc, ["a"])
    with_low = _score(svc, ["a", "b", "c", "d"])
    assert high_only == 2
    assert with_low == 3
    assert with_low >= high_only


# --- weight resolution ------------------------------------------------------


def test_missing_param_defaults_to_weight_3():
    # A changed param absent from decision_params falls back to weight 3.
    svc = _svc({})
    assert _score(svc, ["ghost"]) == 2  # 3 -> Risk 2


def test_duplicate_changed_var_counted_once():
    # Deduplicated before summing, so a repeated name is not double-counted.
    svc = _svc({"a": {"weight": 3}})
    assert _score(svc, ["a", "a"]) == 2  # 3, not 6


# --- configurability --------------------------------------------------------


def test_bands_are_configurable(monkeypatch):
    # Tighten the bands so a single weight-2 change reaches Risk 2.
    monkeypatch.setattr(decision, "WEIGHT_RISK_BANDS", (2, 4))
    svc = _svc({"a": {"weight": 2}})
    assert _score(svc, ["a"]) == 2  # 2 >= t2(2) and < t3(4)

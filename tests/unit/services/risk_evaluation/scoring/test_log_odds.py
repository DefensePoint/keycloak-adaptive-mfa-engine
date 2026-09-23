import math

import pytest

from src.service.risk_evaluation.scoring.log_odds import (
    LogOddsScorer,
    LogOddsResult,
    MAX_RISK_EVIDENCE,
)


def _params(*names, weight=3, enabled=True):
    """Build a decision_params dict for the given parameter names."""
    return {name: {"weight": weight, "enabled": enabled} for name in names}


def test_neutral_context_with_trusting_bias_is_risk1():
    """No changes + neutral credibility + trusting bias => low probability => ACR 1."""
    scorer = LogOddsScorer(
        decision_params=_params("device", "ip_address", "browser"),
        bias=-3.9,
    )
    result = scorer.score(
        changed_vars=[],
        device_credibility=0.5,
        net_loc_credibility=0.5,
    )
    assert isinstance(result, LogOddsResult)
    assert result.risk_level == 1
    assert 0.0 <= result.probability < 0.3


def test_many_changed_high_weight_params_escalate():
    """A pile of changed weight-3 signals overcomes a trusting bias and escalates."""
    names = ["device", "ip_address", "browser", "operating_system", "system_language"]
    scorer = LogOddsScorer(decision_params=_params(*names), bias=-3.9)
    result = scorer.score(
        changed_vars=names,
        device_credibility=0.2,
        net_loc_credibility=0.2,
    )
    assert result.risk_level >= 3
    assert result.probability > 0.6


def test_stable_identity_lowers_risk_vs_changed():
    """Same signal stable vs changed must not increase probability when stable."""
    params = _params("device", "ip_address")
    stable = LogOddsScorer(params, bias=-2.0).score([], 0.5, 0.5)
    changed = LogOddsScorer(params, bias=-2.0).score(["device", "ip_address"], 0.5, 0.5)
    assert stable.probability < changed.probability
    # Stable identity signals contribute negative (trust) evidence.
    assert stable.evidence < 0


def test_changed_param_contributes_positive_evidence_scaled_by_weight():
    high = LogOddsScorer(_params("device", weight=3), bias=0.0).score(
        ["device"], 0.5, 0.5
    )
    low = LogOddsScorer(_params("device", weight=1), bias=0.0).score(
        ["device"], 0.5, 0.5
    )
    # weight-3 changed device contributes full MAX_RISK_EVIDENCE.
    assert high.contributions["device"] == pytest.approx(MAX_RISK_EVIDENCE)
    # weight-1 contributes a third of it.
    assert low.contributions["device"] == pytest.approx(MAX_RISK_EVIDENCE / 3)
    assert high.probability > low.probability


def test_high_credibility_pushes_evidence_negative():
    scorer = LogOddsScorer(_params("device"), bias=0.0)
    trusted = scorer.score([], device_credibility=1.0, net_loc_credibility=1.0)
    untrusted = scorer.score([], device_credibility=0.0, net_loc_credibility=0.0)
    assert trusted.contributions["__credibility"] < 0
    assert untrusted.contributions["__credibility"] > 0
    assert trusted.probability < untrusted.probability


def test_bias_calibration_shifts_probability():
    """A more negative bias (more trusting deployment) yields a lower probability."""
    params = _params("device", "ip_address")
    public = LogOddsScorer(params, bias=-6.9).score(["device"], 0.5, 0.5)
    high_security = LogOddsScorer(params, bias=-2.2).score(["device"], 0.5, 0.5)
    assert public.probability < high_security.probability


def test_disabled_params_are_ignored():
    enabled = LogOddsScorer(_params("device", enabled=True), bias=0.0).score(
        ["device"], 0.5, 0.5
    )
    disabled = LogOddsScorer(_params("device", enabled=False), bias=0.0).score(
        ["device"], 0.5, 0.5
    )
    assert "device" in enabled.contributions
    assert "device" not in disabled.contributions


def test_meta_key_is_ignored():
    params = _params("device")
    params["__meta"] = {"id": "abc"}
    result = LogOddsScorer(params, bias=0.0).score([], 0.5, 0.5)
    assert "__meta" not in result.contributions


def test_probability_to_risk_level_bands():
    scorer = LogOddsScorer(_params("device"), bias=0.0, thresholds=(0.3, 0.6, 0.85))
    assert scorer._probability_to_risk_level(0.10) == 1
    assert scorer._probability_to_risk_level(0.30) == 2
    assert scorer._probability_to_risk_level(0.59) == 2
    assert scorer._probability_to_risk_level(0.60) == 3
    assert scorer._probability_to_risk_level(0.84) == 3
    assert scorer._probability_to_risk_level(0.85) == 4
    assert scorer._probability_to_risk_level(0.99) == 4


def test_logistic_matches_formula():
    scorer = LogOddsScorer(_params("device"), bias=0.0)
    for x in (-10.0, -1.0, 0.0, 1.0, 10.0):
        assert scorer._logistic(x) == pytest.approx(1.0 / (1.0 + math.exp(-x)))


def test_logistic_does_not_overflow_on_extremes():
    scorer = LogOddsScorer(_params("device"), bias=0.0)
    assert scorer._logistic(1000.0) == pytest.approx(1.0)
    assert scorer._logistic(-1000.0) == pytest.approx(0.0)


@pytest.mark.parametrize("bad", [(0.6, 0.3, 0.85), (0.3, 0.6), (-0.1, 0.5, 0.9), "x"])
def test_invalid_thresholds_raise(bad):
    with pytest.raises(ValueError):
        LogOddsScorer(_params("device"), bias=0.0, thresholds=bad)


def test_unconfigured_changed_flag_still_scores():
    """An anomaly flag not present in decision_params still adds risk evidence."""
    scorer = LogOddsScorer(_params("device"), bias=0.0)
    result = scorer.score(["impossible_travel"], 0.5, 0.5)
    assert result.contributions["impossible_travel"] == pytest.approx(MAX_RISK_EVIDENCE)

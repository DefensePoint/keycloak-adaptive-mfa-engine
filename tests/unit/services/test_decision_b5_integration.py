"""B5 integration test — the DBSCAN GEOLOC_RADIUS fix through the real pipeline.

Proves that the fix (get_geo_cluster_label now clusters at the configured
GEOLOC_RADIUS instead of a hardcoded 1 km) is exercised by the REAL pipeline:
real EvalRisk.process() -> real process_geo_cluster_label -> real
ClusteringService.get_geo_cluster_label, and that the resulting label is then
correctly turned into (or kept out of) changed_vars by the real
DecisionService.__detect_param_change_short_term.

No mocking of EvalRisk, the geo-cluster check, or the change-detection logic; no
live Redis/DB/network. GEOLOC_RADIUS is pinned via monkeypatch so the test does
not depend on the ambient environment.
"""

import pandas as pd

from src.service import clustering
from src.service.decision import DecisionService
from src.service.risk_evaluation import EvalRisk

_BASE = 1_700_000_000_000  # fixed epoch ms; no wall clock

# Six logins scattered across ONE metro area (~5-50 km apart, all within 100 km),
# NOT identical coordinates — the range the hardcoded 1 km epsilon mishandled.
_METRO_HISTORY = [
    {"lat": 40.70, "long": -74.00, "event_time": _BASE},
    {"lat": 40.75, "long": -74.20, "event_time": _BASE},
    {"lat": 40.65, "long": -73.90, "event_time": _BASE},
    {"lat": 40.85, "long": -74.30, "event_time": _BASE},
    {"lat": 40.60, "long": -73.80, "event_time": _BASE},
    {"lat": 40.90, "long": -74.10, "event_time": _BASE},
]
_SAME_METRO_CURRENT = {"lat": 40.72, "long": -74.05, "event_time": _BASE + 100_000}
_FAR_CURRENT = {"lat": 35.6762, "long": 139.6503, "event_time": _BASE + 100_000}  # Tokyo


def _eval(current):
    df = pd.DataFrame(_METRO_HISTORY)
    return EvalRisk(
        df_user=df,
        last_decision=2,
        second_last_decision=2,
        previous_event_dict=_METRO_HISTORY[0],
        current_event_dict=current,
        enabled_params=["geolocation_cluster_label"],
    ).process()


def _changed_vars(risk_eval_vars):
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = {"geolocation_cluster_label": {"enabled": True, "weight": 3}}
    return svc._DecisionService__detect_param_change_short_term(risk_eval_vars)


def test_eval_risk_same_metro_is_trend_through_fixed_radius(monkeypatch):
    monkeypatch.setattr(clustering, "GEOLOC_RADIUS", 100)
    rev = _eval(_SAME_METRO_CURRENT)
    # Real EvalRisk -> real fixed clustering: same-metro login is NOT anomalous.
    assert rev["geolocation_cluster_label"] == "TREND"


def test_eval_risk_far_location_is_anomalous_through_pipeline(monkeypatch):
    monkeypatch.setattr(clustering, "GEOLOC_RADIUS", 100)
    rev = _eval(_FAR_CURRENT)
    # A genuinely distant login (Tokyo vs a NYC-metro history) is still ANOMALOUS.
    assert rev["geolocation_cluster_label"] == "ANOMALOUS"


def test_same_metro_does_not_inflate_changed_vars(monkeypatch):
    monkeypatch.setattr(clustering, "GEOLOC_RADIUS", 100)
    rev = _eval(_SAME_METRO_CURRENT)
    # The fix's payoff: a same-metro login no longer contributes a false
    # geolocation_cluster_label hazard to the decision.
    assert "geolocation_cluster_label" not in _changed_vars(rev)


def test_far_location_flags_changed_vars(monkeypatch):
    monkeypatch.setattr(clustering, "GEOLOC_RADIUS", 100)
    rev = _eval(_FAR_CURRENT)
    assert "geolocation_cluster_label" in _changed_vars(rev)

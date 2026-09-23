import pandas as pd

from src.service.clustering import ClusteringService
from src.service import clustering

# Small explicit feature set so the behaviour under test is easy to reason about.
# Production uses ALLOWED_CLUSTERING_PARAMS; the mechanics are identical.
EVENT_FEATURES = ["browser", "operating_system"]


def _history(rows):
    return pd.DataFrame(rows)


# --- Event clustering: classify the CURRENT login by cluster membership ---------


def test_event_never_seen_pattern_is_anomalous():
    history = _history({"browser": ["chrome"] * 8, "operating_system": ["windows"] * 8})
    current = {"browser": "firefox", "operating_system": "linux"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES)
        == "ANOMALOUS"
    )


def test_event_matching_dominant_pattern_is_not_anomalous():
    history = _history({"browser": ["chrome"] * 8, "operating_system": ["windows"] * 8})
    current = {"browser": "chrome", "operating_system": "windows"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "TREND"
    )


def test_event_minority_recurring_pattern_is_rare():
    history = _history(
        {
            "browser": ["chrome"] * 5 + ["safari"] * 3,
            "operating_system": ["windows"] * 5 + ["mac"] * 3,
        }
    )
    current = {"browser": "safari", "operating_system": "mac"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "RARE"
    )


def test_event_scores_current_login_not_oldest_history_row():
    """Regression for the [-1]-on-history bug: an odd first/oldest row must not
    drive the result; only the CURRENT login does."""
    history = _history(
        {
            "browser": ["opera"] + ["chrome"] * 7,
            "operating_system": ["solaris"] + ["windows"] * 7,
        }
    )
    current = {"browser": "chrome", "operating_system": "windows"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "TREND"
    )


def test_event_classification_is_reproducible():
    history = _history({"browser": ["chrome"] * 6, "operating_system": ["windows"] * 6})
    current = {"browser": "firefox", "operating_system": "linux"}
    results = {
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES)
        for _ in range(5)
    }
    assert results == {"ANOMALOUS"}


def test_event_dominant_in_large_history_is_trend():
    history = _history(
        {
            "browser": ["chrome"] * 48 + ["safari"] * 2,
            "operating_system": ["windows"] * 48 + ["mac"] * 2,
        }
    )
    current = {"browser": "chrome", "operating_system": "windows"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "TREND"
    )


# --- Geo clustering: classify the CURRENT login's location ----------------------


def test_geo_far_location_is_anomalous():
    history = _history({"lat": [40.7128] * 6, "long": [-74.0060] * 6})  # New York
    current = {"lat": 35.6762, "long": 139.6503}  # Tokyo
    assert ClusteringService.get_geo_cluster_label(history, current) == "ANOMALOUS"


def test_geo_usual_location_is_not_anomalous():
    history = _history({"lat": [40.7128] * 6, "long": [-74.0060] * 6})
    current = {"lat": 40.7129, "long": -74.0061}  # essentially the same place
    assert ClusteringService.get_geo_cluster_label(history, current) == "TREND"


def test_geo_secondary_smaller_location_is_rare():
    history = _history(
        {
            "lat": [40.7128] * 6 + [42.3601, 42.3602],  # NYC x6, Boston x2
            "long": [-74.0060] * 6 + [-71.0589, -71.0590],
        }
    )
    current = {"lat": 42.3601, "long": -71.0589}  # Boston
    assert ClusteringService.get_geo_cluster_label(history, current) == "RARE"


def test_geo_same_metro_area_is_not_anomalous(monkeypatch):
    """Logins scattered across one metro area (roughly 5-50 km apart, all within
    the configured GEOLOC_RADIUS) must cluster together and NOT be flagged ANOMALOUS.

    Regression for the bug where get_geo_cluster_label ignored GEOLOC_RADIUS and
    always clustered at a hardcoded 1 km epsilon, turning ordinary intra-metro
    spread into DBSCAN noise (label -1) and a false ANOMALOUS."""
    monkeypatch.setattr(clustering, "GEOLOC_RADIUS", 100)
    history = _history(
        {
            "lat": [40.70, 40.75, 40.65, 40.85, 40.60, 40.90],
            "long": [-74.00, -74.20, -73.90, -74.30, -73.80, -74.10],
        }
    )
    current = {"lat": 40.72, "long": -74.05}  # same metro area
    assert ClusteringService.get_geo_cluster_label(history, current) == "TREND"


# --- Defensive edge cases (imperfect production data) ---------------------------


def test_geo_failed_geocode_current_is_trend():
    """A login that could not be geolocated arrives as (0,0); location cannot be
    assessed, so it must NOT be flagged ANOMALOUS."""
    history = _history({"lat": [40.7128] * 6, "long": [-74.0060] * 6})
    current = {"lat": 0.0, "long": 0.0}
    assert ClusteringService.get_geo_cluster_label(history, current) == "TREND"


def test_geo_missing_current_coords_is_trend():
    history = _history({"lat": [40.7128] * 6, "long": [-74.0060] * 6})
    current = {"long": -74.0}  # 'lat' missing
    assert ClusteringService.get_geo_cluster_label(history, current) == "TREND"


def test_geo_history_with_nan_does_not_crash():
    history = _history(
        {"lat": [40.7128, None, 40.7128, 40.7128], "long": [-74.0060] * 4}
    )
    current = {"lat": 40.7128, "long": -74.0060}
    assert ClusteringService.get_geo_cluster_label(history, current) == "TREND"


def test_event_missing_current_feature_does_not_crash():
    history = _history({"browser": ["chrome"] * 6, "operating_system": ["windows"] * 6})
    current = {"browser": "chrome"}  # 'operating_system' missing
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "TREND"
    )


def test_event_history_missing_feature_column_does_not_crash():
    history = _history({"browser": ["chrome"] * 6})  # no 'operating_system' column
    current = {"browser": "chrome", "operating_system": "windows"}
    assert (
        ClusteringService.get_cluster_label(history, current, EVENT_FEATURES) == "TREND"
    )

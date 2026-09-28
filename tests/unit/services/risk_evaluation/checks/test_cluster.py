import pandas as pd

from src.service.risk_evaluation.checks.cluster import process_cluster_label


def test_returns_service_classification(mocker):
    """The check is now a thin wrapper: it returns the service's classification
    directly (no arbitrary-number lookup table)."""
    mocker.patch(
        "src.service.clustering.ClusteringService.get_cluster_label",
        return_value="ANOMALOUS",
    )
    df = pd.DataFrame({"browser": ["chrome", "chrome"]})

    assert process_cluster_label(df, {"browser": "firefox"}) == "ANOMALOUS"


def test_forwards_history_and_current_event(mocker):
    spy = mocker.patch(
        "src.service.clustering.ClusteringService.get_cluster_label",
        return_value="TREND",
    )
    df = pd.DataFrame({"browser": ["chrome"]})
    current = {"browser": "chrome"}

    process_cluster_label(df, current)

    called_args = spy.call_args.args
    assert called_args[0] is df
    assert called_args[1] is current

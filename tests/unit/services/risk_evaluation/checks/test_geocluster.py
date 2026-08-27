import pandas as pd

from src.service.risk_evaluation.checks.geocluster import process_geo_cluster_label


def test_returns_service_classification(mocker):
    mocker.patch(
        "src.service.clustering.ClusteringService.get_geo_cluster_label",
        return_value="ANOMALOUS",
    )
    df = pd.DataFrame({"lat": [40.0], "long": [-74.0]})

    assert process_geo_cluster_label(df, {"lat": 35.0, "long": 139.0}) == "ANOMALOUS"


def test_forwards_history_and_current_event(mocker):
    spy = mocker.patch(
        "src.service.clustering.ClusteringService.get_geo_cluster_label",
        return_value="TREND",
    )
    df = pd.DataFrame({"lat": [40.0], "long": [-74.0]})
    current = {"lat": 40.0, "long": -74.0}

    process_geo_cluster_label(df, current)

    called_args = spy.call_args.args
    assert called_args[0] is df
    assert called_args[1] is current

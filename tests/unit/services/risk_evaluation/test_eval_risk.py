from datetime import datetime
import pandas as pd
from src.service.risk_evaluation.eval_risk import EvalRisk


def test_eval_risk_passing_returning_default_values(mocker):
    fake_now = datetime(2025, 4, 21, 12, 0, 0)
    mock_datetime = mocker.patch("src.service.risk_evaluation.eval_risk.datetime")
    mock_datetime.now.return_value = fake_now

    mock_data_frame = pd.DataFrame(
        {
            "user": [],
        }
    )

    response = EvalRisk(
        df_user=mock_data_frame,
        last_decision=1,
        second_last_decision=2,
        previous_event_dict={},
        current_event_dict={},
        enabled_params=[],
    ).process()

    assert response["impossible_travel"] == "POSSIBLE"
    assert response["anonymous_detection"] == "NOT ANONYMOUS"
    assert response["weekday"] == "Mon"
    assert response["date_time"] == "LOW"
    assert response["time_interval"] == "ACCEPTABLE"
    assert response["inactive_account"] == "ACTIVE"
    assert response["event_cluster_label"] == "TREND"
    assert response["geolocation_cluster_label"] == "TREND"
    assert response["previous_event"] == {}
    assert response["current_event"] == {}
    assert response["second_last_decision"] == 2
    assert response["last_decision"] == 1

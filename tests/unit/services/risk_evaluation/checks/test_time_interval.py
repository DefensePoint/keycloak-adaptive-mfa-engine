import datetime
import time
from numpy import NaN
import pytest
import pandas as pd

from src.service.risk_evaluation.checks.time_interval import process_time_interval


def test_process_time_interval_raises_empty_input(mocker):
    mock_data_frame = pd.DataFrame(
        {
            "event_time": [],
        }
    )

    with pytest.raises(ValueError) as exc:
        process_time_interval(mock_data_frame)

    assert str(exc.value) == "Input DataFrame 'df_user' cannot be empty."


def test_process_time_interval_raises_wrong_column_name(mocker):
    mock_data_frame = pd.DataFrame(
        {
            "event_times": [1, 2],
        }
    )

    with pytest.raises(KeyError) as exc:
        process_time_interval(mock_data_frame)

    assert exc.value.args[0] == "Missing required column 'event_time' in the DataFrame."


def test_process_time_interval_raises_nan_none_values(mocker):
    mock_data_frame = pd.DataFrame(
        {
            "event_time": [1, None],
        }
    )

    with pytest.raises(ValueError) as exc:
        process_time_interval(mock_data_frame)

    assert (
        str(exc.value)
        == "Column 'event_time' contains None/NaN values, which is not allowed."
    )


def test_process_time_interval_raises_non_numeric_values(mocker):
    mock_data_frame = pd.DataFrame(
        {
            "event_time": [1, "value"],
        }
    )

    with pytest.raises(ValueError) as exc:
        process_time_interval(mock_data_frame)

    assert str(exc.value) == "Unable to convert 'event_time' to datetime."


def test_process_time_interval_acceptable(mocker):
    date_time = datetime.datetime(2024, 7, 1)
    unix_now = time.mktime(date_time.timetuple()) * 1e3 + date_time.microsecond / 1e3
    one_day_milliseconds = 87999984

    """
    Logic to create list with the previous ten days in unix timestamp
    """
    unix_days = []
    for _ in range(10):
        unix_days.append(unix_now)
        unix_now -= one_day_milliseconds

    mock_data_frame = pd.DataFrame(
        {
            "event_time": unix_days,
        }
    )

    response = process_time_interval(mock_data_frame)

    assert response == "ACCEPTABLE"


def test_process_time_interval_forbidden(mocker):
    date_time = datetime.datetime(2024, 7, 1)
    unix_now = time.mktime(date_time.timetuple()) * 1e3 + date_time.microsecond / 1e3
    one_day_milliseconds = 87999984

    """
    Have different logins in different times
    """
    mock_data_frame = pd.DataFrame(
        {
            "event_time": [
                unix_now - (one_day_milliseconds * 10),
                unix_now - (one_day_milliseconds * 1),
                unix_now - (one_day_milliseconds * 104),
                unix_now - (one_day_milliseconds * 7),
                unix_now - (one_day_milliseconds * 1000),
                unix_now - (one_day_milliseconds * 554),
            ],
        }
    )

    response = process_time_interval(mock_data_frame)

    assert response == "FORBIDDEN"

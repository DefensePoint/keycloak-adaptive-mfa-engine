import datetime
import time

from numpy import NaN
import pytest
import pandas as pd

from src.service.risk_evaluation.checks.datetime_data import process_datetime_data


def _ts(dt: datetime.datetime) -> float:
    return time.mktime(dt.timetuple()) * 1e3 + dt.microsecond / 1e3


# History: five weekday logins, all at 14:00 (a "normal" hour for this user).
_HISTORY_WEEKDAYS_AT_14 = pd.DataFrame(
    {
        "event_time": [
            _ts(datetime.datetime(2024, 7, 1, 14, 0)),  # Mon
            _ts(datetime.datetime(2024, 7, 2, 14, 0)),  # Tue
            _ts(datetime.datetime(2024, 7, 3, 14, 0)),  # Wed
            _ts(datetime.datetime(2024, 7, 4, 14, 0)),  # Thu
            _ts(datetime.datetime(2024, 7, 5, 14, 0)),  # Fri
        ]
    }
)


def test_high_when_current_login_hour_is_unusual():
    # Current login at 03:00 — an hour this user never logs in at -> HIGH.
    # (Old code scored a stored row's hour and could never see the current 03:00.)
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 8, 3, 0))}

    response = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(), current_event_dict
    )

    assert response == "HIGH"


def test_low_when_current_login_hour_is_common():
    # Current login at 14:00 — the user's usual hour -> LOW.
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 8, 14, 0))}

    response = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(), current_event_dict
    )

    assert response == "LOW"


def test_result_follows_current_login_not_history():
    # Same history, two different current logins -> different verdicts, proving the
    # check scores the CURRENT login's hour rather than a stored row.
    high = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(),
        {"event_time": _ts(datetime.datetime(2024, 7, 8, 3, 0))},
    )
    low = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(),
        {"event_time": _ts(datetime.datetime(2024, 7, 8, 14, 0))},
    )

    assert high == "HIGH"
    assert low == "LOW"


def test_datetime_data_raise_empty_error():
    with pytest.raises(ValueError) as exc:
        process_datetime_data(pd.DataFrame({"event_time": []}), {"event_time": 1})

    assert str(exc.value) == "Input DataFrame 'df_user' cannot be empty."


def test_datetime_data_raise_missing_event_time_column():
    with pytest.raises(KeyError) as exc:
        process_datetime_data(
            pd.DataFrame({"event_timesss": [1745583959201]}), {"event_time": 1}
        )

    assert exc.value.args[0] == "Missing required column 'event_time' in DataFrame."


def test_datetime_data_raise_event_time_column_nan_values():
    with pytest.raises(ValueError) as exc:
        process_datetime_data(
            pd.DataFrame({"event_time": [1745583959201, None, NaN]}), {"event_time": 1}
        )

    assert str(exc.value) == "Column 'event_time' contains None/NaN values."


def test_hour_22_and_23_are_not_conflated():
    # History: 10 weekday logins at 23:00 (the user's common hour), plus a single
    # weekday login at 03:00 and a single weekday login at 22:00 (so hour 22 has
    # only 1 history login, i.e. <= 3, and the histogram branch is entered).
    history = pd.DataFrame(
        {
            "event_time": [
                _ts(datetime.datetime(2025, 1, 6, 23, 0)),  # Mon
                _ts(datetime.datetime(2025, 1, 7, 23, 0)),  # Tue
                _ts(datetime.datetime(2025, 1, 8, 23, 0)),  # Wed
                _ts(datetime.datetime(2025, 1, 9, 23, 0)),  # Thu
                _ts(datetime.datetime(2025, 1, 10, 23, 0)),  # Fri
                _ts(datetime.datetime(2025, 1, 13, 23, 0)),  # Mon
                _ts(datetime.datetime(2025, 1, 14, 23, 0)),  # Tue
                _ts(datetime.datetime(2025, 1, 15, 23, 0)),  # Wed
                _ts(datetime.datetime(2025, 1, 16, 23, 0)),  # Thu
                _ts(datetime.datetime(2025, 1, 17, 23, 0)),  # Fri
                _ts(datetime.datetime(2025, 1, 20, 3, 0)),  # Mon
                _ts(datetime.datetime(2025, 1, 21, 22, 0)),  # Tue
            ]
        }
    )

    # Current login: a weekday at 22:00. This hour is rare (only 1 prior login)
    # relative to the user's dominant 23:00 hour, so it should be scored HIGH.
    # With the old bins=23, range=(0, 23) histogram, hours 22 and 23 fall into the
    # same last bin, so the 22:00 login is wrongly treated as if it shared the
    # 23:00 hour's high frequency and scores LOW.
    current_event_dict = {"event_time": _ts(datetime.datetime(2025, 1, 22, 22, 0))}

    response = process_datetime_data(history.copy(), current_event_dict)

    assert response == "HIGH"

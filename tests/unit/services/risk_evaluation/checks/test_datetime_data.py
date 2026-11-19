import datetime
import time

from numpy import NaN
import pytest
import pandas as pd

from src.service.risk_evaluation.checks.datetime_data import process_datetime_data


def _ts(dt: datetime.datetime) -> float:
    return time.mktime(dt.timetuple()) * 1e3 + dt.microsecond / 1e3


def _weekday_logins(hour: int, n: int, start=datetime.date(2024, 7, 1)) -> list:
    """n login timestamps at ``hour`` on consecutive weekdays (skips weekends)."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() <= 4:
            out.append(_ts(datetime.datetime(d.year, d.month, d.day, hour, 0)))
        d += datetime.timedelta(days=1)
    return out


# History with AMPLE same-day-type samples (>= DATETIME_MIN_SAMPLES): 20 weekday
# logins, all at 14:00 (a "normal" hour for this user). Enough data for the
# time-of-day check to make a call.
_HISTORY_WEEKDAYS_AT_14 = pd.DataFrame({"event_time": _weekday_logins(14, 20)})


def test_high_when_current_login_hour_is_unusual():
    # 20 weekday logins at 14:00, current login at 03:00 -> genuinely unusual
    # hour with enough history to judge it -> HIGH.
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 8, 5, 3, 0))}

    response = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(), current_event_dict
    )

    assert response == "HIGH"


def test_low_when_current_login_hour_is_common():
    # Current login at 14:00 -> the user's usual hour -> LOW.
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 8, 5, 14, 0))}

    response = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(), current_event_dict
    )

    assert response == "LOW"


def test_result_follows_current_login_not_history():
    # Same history, two different current logins -> different verdicts, proving the
    # check scores the CURRENT login's hour rather than a stored row.
    high = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(),
        {"event_time": _ts(datetime.datetime(2024, 8, 5, 3, 0))},
    )
    low = process_datetime_data(
        _HISTORY_WEEKDAYS_AT_14.copy(),
        {"event_time": _ts(datetime.datetime(2024, 8, 5, 14, 0))},
    )

    assert high == "HIGH"
    assert low == "LOW"


def test_low_when_same_day_type_history_too_sparse():
    # Only 5 weekday logins: too little to build a trustworthy hour distribution.
    # An unusual-looking 03:00 login must NOT flag HIGH just because that hour
    # has not been seen yet (the sparse-history false positive this guard fixes).
    sparse = pd.DataFrame({"event_time": _weekday_logins(14, 5)})
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 8, 5, 3, 0))}

    assert process_datetime_data(sparse, current_event_dict) == "LOW"


def test_low_when_no_matching_day_type_history():
    # History is all weekdays; the current login is a weekend at an hour with no
    # prior logins. The matching-day-type set is empty, so the check stays LOW
    # (and never builds an all-NaN histogram).
    weekday_only = pd.DataFrame({"event_time": _weekday_logins(14, 20)})
    saturday_0300 = {"event_time": _ts(datetime.datetime(2024, 8, 3, 3, 0))}  # Sat

    assert process_datetime_data(weekday_only, saturday_0300) == "LOW"


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
    # 20 weekday logins at 23:00 (the user's common hour) plus one weekday login
    # at 22:00, so hour 22 has a single prior login (<= 3, histogram branch) and
    # there is enough same-day-type history (>= 20) to judge it.
    times = _weekday_logins(23, 20)
    times.append(_ts(datetime.datetime(2024, 8, 6, 22, 0)))  # a Tuesday at 22:00
    history = pd.DataFrame({"event_time": times})

    # Current login: a weekday at 22:00. Rare vs the dominant 23:00 hour, so HIGH.
    # A bins=23 histogram would fold hours 22 and 23 into one bin and wrongly
    # score this LOW; bins=24 keeps them distinct.
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 8, 7, 22, 0))}

    assert process_datetime_data(history.copy(), current_event_dict) == "HIGH"

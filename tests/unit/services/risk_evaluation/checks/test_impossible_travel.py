from numpy import NaN
import pytest
import pandas as pd

from src.service.risk_evaluation.checks.impossible_travel import (
    process_impossible_travel,
)

DAY = 86_400_000
T0 = 1745596539832

NYC_LAT, NYC_LONG = 40.7128, -74.0060
LONDON_LAT, LONDON_LONG = 51.5074, -0.1278

# Stored history: three logins from NYC over consecutive days.
_HISTORY_NYC = pd.DataFrame(
    {
        "lat": [NYC_LAT, NYC_LAT, NYC_LAT],
        "long": [NYC_LONG, NYC_LONG, NYC_LONG],
        "event_time": [T0, T0 + DAY, T0 + 2 * DAY],
    }
)
_LAST_STORED_TIME = T0 + 2 * DAY


def test_impossible_when_current_login_is_a_far_jump():
    # Current login from London, 60 seconds after the last NYC login -> impossible.
    current_event_dict = {
        "lat": LONDON_LAT,
        "long": LONDON_LONG,
        "event_time": _LAST_STORED_TIME + 60_000,
    }

    response = process_impossible_travel(_HISTORY_NYC.copy(), current_event_dict)

    assert response == "IMPOSSIBLE"


def test_feasible_when_current_login_is_same_place():
    # Current login from NYC again, a day later -> no meaningful travel -> feasible.
    current_event_dict = {
        "lat": NYC_LAT,
        "long": NYC_LONG,
        "event_time": _LAST_STORED_TIME + DAY,
    }

    response = process_impossible_travel(_HISTORY_NYC.copy(), current_event_dict)

    assert response == "FEASIBLE"


def test_verdict_follows_current_login_not_history():
    # Same history; only the current login differs -> opposite verdicts. Proves the
    # leg INTO the current login is what's measured (old code never saw it).
    impossible = process_impossible_travel(
        _HISTORY_NYC.copy(),
        {"lat": LONDON_LAT, "long": LONDON_LONG, "event_time": _LAST_STORED_TIME + 60_000},
    )
    feasible = process_impossible_travel(
        _HISTORY_NYC.copy(),
        {"lat": NYC_LAT, "long": NYC_LONG, "event_time": _LAST_STORED_TIME + DAY},
    )

    assert impossible == "IMPOSSIBLE"
    assert feasible == "FEASIBLE"


def test_feasible_when_current_login_not_geolocated():
    # Geo lookup failed for the current login (0,0) -> cannot assess -> feasible
    # (avoids a false "impossible jump to the middle of the ocean").
    current_event_dict = {"lat": 0, "long": 0, "event_time": _LAST_STORED_TIME + 60_000}

    response = process_impossible_travel(_HISTORY_NYC.copy(), current_event_dict)

    assert response == "FEASIBLE"


def test_raise_empty_error():
    current_event_dict = {"lat": NYC_LAT, "long": NYC_LONG, "event_time": T0}
    with pytest.raises(ValueError) as exc:
        process_impossible_travel(
            pd.DataFrame({"lat": [], "long": [], "event_time": []}), current_event_dict
        )

    assert str(exc.value) == "Input DataFrame 'df_user' cannot be empty."


def test_raise_missing_some_columns():
    current_event_dict = {"lat": NYC_LAT, "long": NYC_LONG, "event_time": T0}
    with pytest.raises(KeyError) as exc:
        process_impossible_travel(
            pd.DataFrame({"lat": [1], "long": [2], "event_times": [3]}),
            current_event_dict,
        )

    assert exc.value.args[0] == "Missing required columns: {'event_time'}"


def test_raise_none_values():
    current_event_dict = {"lat": NYC_LAT, "long": NYC_LONG, "event_time": T0}
    with pytest.raises(ValueError) as exc:
        process_impossible_travel(
            pd.DataFrame({"lat": [1, NaN], "long": [2, 2], "event_time": [3, 2]}),
            current_event_dict,
        )

    assert (
        str(exc.value)
        == "Column 'lat' contains None/NaN values, which is not allowed."
    )


def test_raise_missing_current_event_field():
    with pytest.raises(ValueError) as exc:
        process_impossible_travel(
            _HISTORY_NYC.copy(), {"lat": NYC_LAT, "long": NYC_LONG}
        )

    assert str(exc.value) == "current_event_dict must contain 'event_time'."


# ---- A1: absolute speed cap + gap-guarded relative test ---------------------

def test_feasible_slow_move_over_long_gap():
    # ~11 km move, 6 hours after the last login. Faster than the user's zero
    # median, but the gap is well beyond the 1h burst window, so it is feasible.
    # (A1 fix: the old relative-only rule flagged this as IMPOSSIBLE.)
    current = {
        "lat": 40.81,
        "long": NYC_LONG,
        "event_time": _LAST_STORED_TIME + 6 * 3600 * 1000,
    }
    assert process_impossible_travel(_HISTORY_NYC.copy(), current) == "FEASIBLE"


def test_impossible_when_absolute_cap_exceeded_even_over_long_gap():
    # NYC -> London (~5570 km) in 2h => ~2785 km/h, above the 900 km/h cap, so
    # impossible regardless of the burst window.
    current = {
        "lat": LONDON_LAT,
        "long": LONDON_LONG,
        "event_time": _LAST_STORED_TIME + 2 * 3600 * 1000,
    }
    assert process_impossible_travel(_HISTORY_NYC.copy(), current) == "IMPOSSIBLE"


def test_impossible_fast_move_within_burst_window():
    # ~200 km move in 20 min => ~595 km/h: under the cap but above the user's
    # median and inside the 1h burst window -> impossible.
    current = {
        "lat": 42.5,
        "long": NYC_LONG,
        "event_time": _LAST_STORED_TIME + 20 * 60 * 1000,
    }
    assert process_impossible_travel(_HISTORY_NYC.copy(), current) == "IMPOSSIBLE"


def test_feasible_same_timestamp_zero_gap():
    # Current login at the exact time of the last stored login -> zero gap ->
    # undefined speed (division by zero). Cannot assess -> feasible (no false
    # "impossible" from an infinite speed).
    current = {
        "lat": LONDON_LAT,
        "long": LONDON_LONG,
        "event_time": _LAST_STORED_TIME,
    }
    assert process_impossible_travel(_HISTORY_NYC.copy(), current) == "FEASIBLE"

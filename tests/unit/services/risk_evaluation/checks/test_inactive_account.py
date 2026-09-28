import datetime
import time

import pytest
import pandas as pd

from src.core.config.environment import DEFAULT_INACTIVE_DAYS
from src.service.risk_evaluation.checks.inactive_account import (
    process_inactive_account,
    resolve_inactive_threshold,
)


def _ts(dt: datetime.datetime) -> float:
    return time.mktime(dt.timetuple()) * 1e3 + dt.microsecond / 1e3


def test_inactive_when_current_login_far_after_last_stored():
    # Latest stored login is 41 days before the current login -> INACTIVE.
    stored = pd.DataFrame(
        {
            "event_time": [
                _ts(datetime.datetime(2024, 5, 20)),
                _ts(datetime.datetime(2024, 5, 21)),  # latest stored
            ]
        }
    )
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 1))}

    assert process_inactive_account(stored, current_event_dict, 40) == "INACTIVE"


def test_active_when_current_login_soon_after_last_stored():
    stored = pd.DataFrame(
        {
            "event_time": [
                _ts(datetime.datetime(2024, 7, 1)),
                _ts(datetime.datetime(2024, 7, 10)),  # latest stored
            ]
        }
    )
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 11))}

    assert process_inactive_account(stored, current_event_dict, 40) == "ACTIVE"


def test_uses_current_login_not_gap_between_stored_events():
    # The two stored events are 50 days apart (old code would call this INACTIVE),
    # but the current login is only 1 day after the latest stored -> ACTIVE.
    stored = pd.DataFrame(
        {
            "event_time": [
                _ts(datetime.datetime(2024, 5, 1)),
                _ts(datetime.datetime(2024, 6, 20)),  # latest stored
            ]
        }
    )
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 6, 21))}

    assert process_inactive_account(stored, current_event_dict, 40) == "ACTIVE"


def test_order_independent_uses_max_stored_time():
    # Frame in descending order; the latest stored login is still found via max().
    stored = pd.DataFrame(
        {
            "event_time": [
                _ts(datetime.datetime(2024, 6, 20)),  # newest, placed first
                _ts(datetime.datetime(2024, 6, 19)),
                _ts(datetime.datetime(2024, 5, 1)),
            ]
        }
    )
    # 41 days after the latest stored (06-20) -> INACTIVE regardless of frame order.
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 31))}

    assert process_inactive_account(stored, current_event_dict, 40) == "INACTIVE"


def test_single_stored_event_is_enough():
    stored = pd.DataFrame({"event_time": [_ts(datetime.datetime(2024, 5, 21))]})
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 1))}

    assert process_inactive_account(stored, current_event_dict, 40) == "INACTIVE"


def test_raises_empty_df():
    with pytest.raises(ValueError) as exc:
        process_inactive_account(
            pd.DataFrame({"event_time": []}), {"event_time": 1}, 40
        )

    assert str(exc.value) == "Input DataFrame 'df_user' cannot be empty."


def test_raises_missing_column():
    with pytest.raises(KeyError) as exc:
        process_inactive_account(
            pd.DataFrame({"event_times": [1, 2]}), {"event_time": 1}, 40
        )

    assert exc.value.args[0] == "Missing required column 'event_time'."


def test_raises_null_event_time():
    with pytest.raises(ValueError) as exc:
        process_inactive_account(
            pd.DataFrame({"event_time": [1, None]}), {"event_time": 1}, 40
        )

    assert str(exc.value) == "Column 'event_time' contains None/NaN values."


def test_raises_missing_current_event_time():
    with pytest.raises(ValueError) as exc:
        process_inactive_account(pd.DataFrame({"event_time": [1, 2]}), {}, 40)

    assert str(exc.value) == "current_event_dict must contain 'event_time'."


@pytest.mark.parametrize(
    "configured",
    [None, 0, -5, "not-a-number", True],
)
def test_resolve_falls_back_to_env_default(configured):
    """Missing, non-positive, non-numeric and boolean values all mean "unset", so
    a malformed stored row can never brick the signal."""
    assert resolve_inactive_threshold(configured) == DEFAULT_INACTIVE_DAYS


def test_resolve_prefers_a_configured_value():
    assert resolve_inactive_threshold(90) == 90


def test_threshold_is_honoured_at_the_boundary():
    """A 41-day gap is INACTIVE at the default 40 but ACTIVE at a realm-configured
    90, which is the whole point of the feature."""
    stored = pd.DataFrame({"event_time": [_ts(datetime.datetime(2024, 5, 21))]})
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 7, 1))}

    assert process_inactive_account(stored, current_event_dict, 40) == "INACTIVE"
    assert process_inactive_account(stored, current_event_dict, 90) == "ACTIVE"


def test_threshold_boundary_is_inclusive():
    """Exactly at the threshold counts as dormant (>=, not >)."""
    stored = pd.DataFrame({"event_time": [_ts(datetime.datetime(2024, 5, 1))]})
    current_event_dict = {"event_time": _ts(datetime.datetime(2024, 5, 31))}

    assert process_inactive_account(stored, current_event_dict, 30) == "INACTIVE"
    assert process_inactive_account(stored, current_event_dict, 31) == "ACTIVE"

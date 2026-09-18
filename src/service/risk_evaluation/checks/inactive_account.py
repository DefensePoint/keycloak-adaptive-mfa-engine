import pandas as pd
from src.core.config.environment import DEFAULT_INACTIVE_DAYS


def resolve_inactive_threshold(configured_days: int | None) -> int:
    """Effective dormancy threshold in days.

    A realm may configure `inactive_days` on its `inactive_account` parameter.
    Anything missing, non-integer, boolean or below 1 means "unset" and falls back
    to the deployment default, so neither a pre-feature config nor a hand-edited
    row can disable or invert the signal. Zero is rejected because it would flag
    every single login as dormant.
    """
    if isinstance(configured_days, bool) or not isinstance(configured_days, int):
        return DEFAULT_INACTIVE_DAYS
    return configured_days if configured_days >= 1 else DEFAULT_INACTIVE_DAYS


def process_inactive_account(
    df_user: pd.DataFrame, current_event_dict: dict, threshold_days: int
) -> str:
    """Determine if a user account is inactive based on time since the last login.

    Dormancy is the gap between the user's most recent *stored* login and the login
    they are attempting *now*. The current login is not yet persisted in the event
    history, so its timestamp is taken from ``current_event_dict`` rather than from
    ``df_user``. The most recent stored login is obtained with ``max()`` on
    ``event_time``, which is independent of how ``df_user`` happens to be ordered.

    Args:
        df_user (pd.DataFrame):
            Stored login history. Must include numeric ``event_time`` and at least
            one row.
        current_event_dict (dict):
            The in-flight login event. Must contain ``event_time``.
        threshold_days (int):
            Dormancy threshold in days, already resolved by
            ``resolve_inactive_threshold``. A gap greater than or equal to this
            many days is reported as INACTIVE.

    Returns:
        str:
            - **"INACTIVE"** if (current login time - last stored login time) is
              greater than or equal to the configured inactive threshold.
            - **"ACTIVE"** otherwise.

    Raises:
        ValueError:
            - If ``df_user`` is empty or ``event_time`` is null/non-numeric.
            - If ``current_event_dict`` lacks a usable ``event_time``.
        KeyError:
            - If the required column ``event_time`` is missing from ``df_user``.
    """
    if df_user.empty:
        raise ValueError("Input DataFrame 'df_user' cannot be empty.")
    if "event_time" not in df_user.columns:
        raise KeyError("Missing required column 'event_time'.")
    if df_user["event_time"].isnull().any():
        raise ValueError("Column 'event_time' contains None/NaN values.")
    if current_event_dict.get("event_time") is None:
        raise ValueError("current_event_dict must contain 'event_time'.")

    try:
        stored_times = pd.to_numeric(df_user["event_time"])
        current_record_time = float(current_event_dict["event_time"])
    except (ValueError, TypeError) as e:
        raise ValueError("'event_time' must contain numeric data.") from e

    # Most recent stored login (order-independent — no reliance on the frame's sort).
    last_login_time = stored_times.max()
    Dt = current_record_time - last_login_time

    one_day_milliseconds = 86_400_000  # 24 * 60 * 60 * 1000
    inactive_threshold = threshold_days * one_day_milliseconds

    state = "INACTIVE" if abs(Dt) >= inactive_threshold else "ACTIVE"

    return state

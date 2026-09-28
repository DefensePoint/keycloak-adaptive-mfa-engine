import pandas as pd
from datetime import datetime


def process_time_interval(df_user: pd.DataFrame) -> str:
    """
    Determine whether the most recent time interval in user activity is
    acceptable or forbidden.

    Args:
        df_user (pd.DataFrame):
            A DataFrame containing user login event data. Must include:
            - `event_time`: Unix timestamps in milliseconds since epoch.
        realm_id (str):
            A string identifier for a "realm".
        group_id (str):
            A string identifier for a "group".

    Returns:
        str:
            - **"ACCEPTABLE"** if the most recent time interval is at or above
              the median of all intervals.
            - **"FORBIDDEN"** otherwise.

    Raises:
        ValueError: If `df_user` is None, empty, or lacks valid data in `event_time`.
        KeyError: If the required column `event_time` is missing.
    """
    if df_user.empty:
        raise ValueError("Input DataFrame 'df_user' cannot be empty.")
    if "event_time" not in df_user.columns:
        raise KeyError("Missing required column 'event_time' in the DataFrame.")
    if df_user["event_time"].isnull().any():
        raise ValueError(
            "Column 'event_time' contains None/NaN values, which is not allowed."
        )

    try:
        df_user["date_time"] = pd.to_datetime(
            df_user["event_time"].apply(
                lambda x: datetime.fromtimestamp(int(x) / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3]
            )
        )
    except (ValueError, TypeError) as e:
        raise ValueError("Unable to convert 'event_time' to datetime.") from e

    df_user = df_user.sort_values(by="date_time")

    df_user["dt"] = (
        df_user["date_time"]
        .diff()
        .apply(lambda x: x.total_seconds() if x is not None else 0)
        .fillna(0)
        .astype(float)
    )

    median_dt = df_user["dt"].quantile(0.5)

    latest_dt = abs(df_user["dt"].iloc[-1])

    return "ACCEPTABLE" if latest_dt >= median_dt else "FORBIDDEN"

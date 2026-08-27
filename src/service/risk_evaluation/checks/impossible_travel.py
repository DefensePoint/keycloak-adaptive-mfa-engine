import pandas as pd
import haversine as hs
from datetime import datetime

from src.core.config.environment import (
    IMPOSSIBLE_TRAVEL_MAX_SPEED_KMH,
    IMPOSSIBLE_TRAVEL_BURST_GAP_MINUTES,
)


def process_impossible_travel(
    df_user: pd.DataFrame, current_event_dict: dict
) -> str:
    """Determine whether reaching the CURRENT login required impossible travel.

    Builds the user's location trajectory from stored logins (oldest -> newest) and
    appends the in-flight login as the final point, so the final "leg" is the trip
    from the most recent stored login to the login being attempted now. The current
    login is not yet persisted in the event history, so its coordinates/time are taken
    from ``current_event_dict``. The final leg's speed is compared against the median
    speed of the trajectory: faster than the user's typical speed -> "IMPOSSIBLE".

    Args:
        df_user (pd.DataFrame):
            Stored login history. Must include 'lat', 'long', 'event_time'.
        current_event_dict (dict):
            The in-flight login event. Must include 'lat', 'long', 'event_time'.

    Returns:
        str:
            "FEASIBLE" if the final leg's speed is at or below the median speed,
            otherwise "IMPOSSIBLE". Also "FEASIBLE" if the current login could not be
            geolocated (lat/long == 0,0), since travel cannot be assessed.

    Raises:
        ValueError:
            - If df_user is empty, has null values, or coords cannot be converted.
            - If current_event_dict is missing a required field.
        KeyError:
            - If any required column is missing from df_user.
    """
    if df_user.empty:
        raise ValueError("Input DataFrame 'df_user' cannot be empty.")

    required_columns = {"lat", "long", "event_time"}
    if not required_columns.issubset(df_user.columns):
        missing = required_columns - set(df_user.columns)
        raise KeyError(f"Missing required columns: {missing}")

    for col in required_columns:
        if df_user[col].isnull().any():
            raise ValueError(
                f"Column '{col}' contains None/NaN values, which is not allowed."
            )

    for key in required_columns:
        if current_event_dict.get(key) is None:
            raise ValueError(f"current_event_dict must contain '{key}'.")

    try:
        current_lat = float(current_event_dict["lat"])
        current_long = float(current_event_dict["long"])
    except (ValueError, TypeError) as e:
        raise ValueError("Unable to convert current 'lat'/'long' to float.") from e

    # If the current login could not be geolocated, travel cannot be assessed.
    if current_lat == 0.0 and current_long == 0.0:
        return "FEASIBLE"

    # Trajectory: stored history oldest -> newest, with the current login appended
    # last so the final leg is the trip INTO the login being attempted.
    trajectory = df_user.sort_values("event_time")[
        ["lat", "long", "event_time"]
    ].copy()

    try:
        trajectory["lat"] = trajectory["lat"].astype(float)
        trajectory["long"] = trajectory["long"].astype(float)
    except ValueError as e:
        raise ValueError("Unable to convert 'lat' or 'long' columns to float.") from e

    current_row = pd.DataFrame(
        [
            {
                "lat": current_lat,
                "long": current_long,
                "event_time": current_event_dict["event_time"],
            }
        ]
    )
    trajectory = pd.concat([trajectory, current_row], ignore_index=True)

    trajectory["loc"] = list(zip(trajectory["lat"], trajectory["long"]))

    distances = [0.0]
    for i in range(1, len(trajectory)):
        prev_loc = trajectory["loc"].iloc[i - 1]
        current_loc = trajectory["loc"].iloc[i]
        distances.append(hs.haversine(prev_loc, current_loc, unit=hs.Unit.METERS))
    trajectory["Dx"] = distances

    try:
        trajectory["date_time"] = pd.to_datetime(
            trajectory["event_time"].apply(
                lambda x: datetime.fromtimestamp(int(x) / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3]
            )
        )
    except (ValueError, TypeError) as e:
        raise ValueError("Unable to convert 'event_time' to datetime.") from e

    trajectory["dt"] = (
        trajectory["date_time"]
        .diff()
        .apply(lambda x: x.total_seconds() if x is not None else 0)
        .fillna(0)
        .astype(float)
    )

    trajectory["v"] = (trajectory["Dx"] / trajectory["dt"]).fillna(0.0)

    final_speed = trajectory["v"].iloc[-1]  # speed of the leg INTO the current login
    median_speed = trajectory["v"].median()
    gap_seconds = float(trajectory["dt"].iloc[-1])  # time into the current login

    # Same-timestamp logins (clock skew / sub-second) give a zero gap, so the
    # leg speed is undefined (division by zero -> inf). Travel cannot be
    # assessed, so treat it as feasible rather than a false "impossible".
    if gap_seconds <= 0:
        return "FEASIBLE"

    cap_mps = IMPOSSIBLE_TRAVEL_MAX_SPEED_KMH / 3.6
    burst_seconds = IMPOSSIBLE_TRAVEL_BURST_GAP_MINUTES * 60

    # Absolute physical cap: no legitimate travel exceeds this, regardless of the
    # user's own history (fixes "median is ~0, so any movement looks impossible").
    if final_speed > cap_mps:
        return "IMPOSSIBLE"

    # Relative anomaly: faster than the user's typical speed, but only when the
    # two logins are close in time (a burst). A slower move spread across a long
    # gap is physically feasible even if it beats the user's median.
    if final_speed > median_speed and gap_seconds < burst_seconds:
        return "IMPOSSIBLE"

    return "FEASIBLE"

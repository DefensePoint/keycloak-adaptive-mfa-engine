import pandas as pd
import numpy as np
import scipy.stats
from sklearn import preprocessing
from datetime import datetime


def process_datetime_data(df_user: pd.DataFrame, current_event_dict: dict) -> str:
    """
    Merge date-time processing routines to assess user login frequency.

    This function handles both:
    1. Extraction of the current hour and day type from event timestamps.
    2. Analyzing login behavior to determine a potential "hazard" level
       (e.g., "HIGH" or "LOW") based on statistical likelihood.

    The day type is defined as:
    - 1 for weekdays (Monday=0 through Friday=4)
    - 0 for weekends (Saturday=5, Sunday=6)

    Args:
        df_user (pd.DataFrame):
            A DataFrame containing user event data with a column named "event_time"
            representing Unix time (in milliseconds). Additional columns for
            "lat", "long", etc., may exist but are not directly used here.

    Returns:
        str:
            "HIGH" or "LOW" depending on the computed hazard level, or "LOW".

    Raises:
        ValueError:
            - If `df_user` is None.
            - If `df_user` is empty.
            - If any of the required columns have null values or cannot be processed.
        KeyError:
            - If the required column "event_time" is missing.
    """
    if df_user.empty:
        raise ValueError("Input DataFrame 'df_user' cannot be empty.")

    if "event_time" not in df_user.columns:
        raise KeyError("Missing required column 'event_time' in DataFrame.")

    if df_user["event_time"].isnull().any():
        raise ValueError("Column 'event_time' contains None/NaN values.")

    try:
        df_user["date_time"] = pd.to_datetime(
            df_user["event_time"].apply(
                lambda x: datetime.fromtimestamp(int(x) / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        )
    except (ValueError, TypeError) as e:
        raise ValueError("Unable to convert 'event_time' to datetime.") from e

    df_user["hour"] = df_user["date_time"].apply(lambda x: x.hour)
    df_user["week_day"] = df_user["date_time"].apply(lambda x: x.weekday())
    df_user["day_type"] = df_user["week_day"].apply(lambda x: 1 if x <= 4 else 0)

    # The hour/day-of-week being scored is the CURRENT login's, not a stored row's.
    # The current login is not yet persisted in df_user, so derive it from the
    # in-flight event (df_user above is the historical distribution to score against).
    if current_event_dict.get("event_time") is None:
        raise ValueError("current_event_dict must contain 'event_time'.")
    current_dt = datetime.fromtimestamp(int(current_event_dict["event_time"]) / 1000)
    current_hour = current_dt.hour
    current_day_type = 1 if current_dt.weekday() <= 4 else 0

    n_logins_current_hour = df_user[df_user["hour"] == current_hour].shape[0]

    if n_logins_current_hour <= 3:
        df_prob = df_user[df_user["day_type"] == current_day_type]

        T = np.linspace(0, 23, 24)
        hist = np.histogram(
            df_prob["hour"].values, bins=24, range=(0, 24), density=True
        )
        hist_dist = scipy.stats.rv_histogram(hist, density=True)

        pdf = hist_dist.pdf(T)

        scaler = preprocessing.MinMaxScaler()
        pdf_scaled = scaler.fit_transform(pdf.reshape(-1, 1)).flatten()

        prob_hazard = 1 - pdf_scaled

        hazard_threshold = 0.6
        if prob_hazard[current_hour] >= hazard_threshold:
            return "HIGH"
        else:
            return "LOW"

    return "LOW"

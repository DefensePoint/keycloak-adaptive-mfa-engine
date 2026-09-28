import logging

import numpy as np
import pandas as pd

from src.core.config.environment import (
    LOGIN_FAILURE_WINDOW_MINUTES,
    LOGIN_FAILURE_RATE_THRESHOLD,
    LOGIN_FAILURE_DISTINCT_IP_THRESHOLD,
    LOGIN_FAILURE_DOS_CAP,
)

# Secondary tuning (fixed; the primary thresholds above are env-configurable).
# Activity burst: this many failures inside this short window.
BURST_COUNT = 10
BURST_WINDOW_MS = 60 * 1000
# Bot-like timing regularity: with at least this many samples, an inter-arrival
# coefficient of variation below this value is "too regular" to be human.
REGULARITY_MIN_SAMPLES = 5
REGULARITY_CV_THRESHOLD = 0.15


def process_login_failure(df_failures: pd.DataFrame, now_ms: float | None = None) -> str:
    """Classify a user's recent login-failure history as SUSPICIOUS or NORMAL.

    Evaluates four independent patterns over failures within the configured time
    window; any one of them is sufficient to flag the user:

    1. High failure rate    - failures in window >= ``LOGIN_FAILURE_RATE_THRESHOLD``.
    2. Distributed brute-force - distinct source IPs in window >=
       ``LOGIN_FAILURE_DISTINCT_IP_THRESHOLD``.
    3. Bot-like regularity   - inter-arrival times are unnaturally even
       (coefficient of variation < ``REGULARITY_CV_THRESHOLD``).
    4. Activity burst        - ``BURST_COUNT`` failures within ``BURST_WINDOW_MS``.

    A hard ceiling (``LOGIN_FAILURE_DOS_CAP``) flags regardless of pattern as a
    basic DoS / credential-stuffing mitigation.

    Args:
        df_failures:
            DataFrame of the user's failed authentication events. Expected columns:
            ``event_time`` (epoch milliseconds) and ``ip_address``. An empty or
            ``None`` frame yields "NORMAL".
        now_ms:
            Reference "current" time in epoch milliseconds. Defaults to the latest
            event in the frame (or the current wall-clock if the frame is empty).

    Returns:
        str: "SUSPICIOUS" if any pattern matches, otherwise "NORMAL".
    """
    if df_failures is None or df_failures.empty:
        return "NORMAL"
    if "event_time" not in df_failures.columns:
        return "NORMAL"

    times = pd.to_numeric(df_failures["event_time"], errors="coerce").dropna()
    if times.empty:
        return "NORMAL"

    reference = now_ms if now_ms is not None else float(times.max())
    window_start = reference - LOGIN_FAILURE_WINDOW_MINUTES * 60 * 1000

    in_window = df_failures.loc[times[times >= window_start].index]
    window_times = np.sort(
        pd.to_numeric(in_window["event_time"], errors="coerce").dropna().to_numpy()
    )
    count = window_times.size

    if count == 0:
        return "NORMAL"

    patterns = []

    if count >= LOGIN_FAILURE_DOS_CAP:
        patterns.append("dos_cap")
    if count >= LOGIN_FAILURE_RATE_THRESHOLD:
        patterns.append("high_failure_rate")

    if "ip_address" in in_window.columns:
        distinct_ips = in_window["ip_address"].dropna().nunique()
        if distinct_ips >= LOGIN_FAILURE_DISTINCT_IP_THRESHOLD:
            patterns.append("distributed_brute_force")

    if count >= BURST_COUNT:
        # Any window of BURST_COUNT consecutive failures spanning <= BURST_WINDOW_MS.
        spans = window_times[BURST_COUNT - 1 :] - window_times[: count - BURST_COUNT + 1]
        if np.any(spans <= BURST_WINDOW_MS):
            patterns.append("activity_burst")

    if count >= REGULARITY_MIN_SAMPLES:
        intervals = np.diff(window_times)
        mean = float(np.mean(intervals)) if intervals.size else 0.0
        if mean > 0:
            cv = float(np.std(intervals)) / mean
            if cv < REGULARITY_CV_THRESHOLD:
                patterns.append("bot_like_regularity")

    if patterns:
        logging.info(
            "Login-failure analysis: %d failures in window, patterns=%s => SUSPICIOUS",
            count,
            patterns,
        )
        return "SUSPICIOUS"

    logging.debug("Login-failure analysis: %d failures in window => NORMAL", count)
    return "NORMAL"

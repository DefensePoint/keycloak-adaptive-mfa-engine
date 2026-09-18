import logging

import pandas as pd

from src.core.config.environment import (
    CONCURRENT_SESSION_ACTIVE_WINDOW_MINUTES,
    CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD,
    CONCURRENT_SESSION_PER_IP_THRESHOLD,
)


def process_concurrent_session(df_logins: pd.DataFrame, now_ms: float | None = None) -> str:
    """Detect concurrent-session anomalies from recent successful logins.

    Active sessions are approximated by successful logins within the active window
    (the engine does not own Keycloak's session store, so recent logins are the
    best available proxy). Two patterns flag the user:

    1. Credential sharing - distinct source IPs in the active window >=
       ``CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD`` (same account logging in from
       several places at once).
    2. Bot sessions-per-IP - logins from a single IP in the active window >=
       ``CONCURRENT_SESSION_PER_IP_THRESHOLD`` (automation hammering from one host).

    Args:
        df_logins:
            DataFrame of the user's successful login events, ideally including the
            current attempt. Expected columns: ``event_time`` (epoch milliseconds)
            and ``ip_address``. An empty or ``None`` frame yields "NORMAL".
        now_ms:
            Reference "current" time in epoch milliseconds. Defaults to the latest
            event in the frame.

    Returns:
        str: "SUSPICIOUS" if either pattern matches, otherwise "NORMAL".
    """
    if df_logins is None or df_logins.empty:
        return "NORMAL"
    if "event_time" not in df_logins.columns or "ip_address" not in df_logins.columns:
        return "NORMAL"

    times = pd.to_numeric(df_logins["event_time"], errors="coerce")
    valid = df_logins.assign(_t=times).dropna(subset=["_t"])
    if valid.empty:
        return "NORMAL"

    reference = now_ms if now_ms is not None else float(valid["_t"].max())
    window_start = reference - CONCURRENT_SESSION_ACTIVE_WINDOW_MINUTES * 60 * 1000

    active = valid[valid["_t"] >= window_start]
    ips = active["ip_address"].dropna()
    if ips.empty:
        return "NORMAL"

    patterns = []

    distinct_ips = ips.nunique()
    if distinct_ips >= CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD:
        patterns.append(f"credential_sharing(distinct_ips={distinct_ips})")

    max_per_ip = int(ips.value_counts().max())
    if max_per_ip >= CONCURRENT_SESSION_PER_IP_THRESHOLD:
        patterns.append(f"bot_sessions_per_ip(max={max_per_ip})")

    if patterns:
        logging.info("Concurrent-session analysis: patterns=%s => SUSPICIOUS", patterns)
        return "SUSPICIOUS"

    logging.debug(
        "Concurrent-session analysis: distinct_ips=%d max_per_ip=%d => NORMAL",
        distinct_ips,
        max_per_ip,
    )
    return "NORMAL"

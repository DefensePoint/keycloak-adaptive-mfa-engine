import pandas as pd

from src.service.risk_evaluation.checks import concurrent_session
from src.service.risk_evaluation.checks.concurrent_session import (
    process_concurrent_session,
)

NOW = 1_700_000_000_000  # fixed reference time in ms
MINUTE = 60 * 1000


def _df(rows):
    return pd.DataFrame(rows, columns=["event_time", "ip_address"])


def test_empty_or_none_is_normal():
    assert process_concurrent_session(None, now_ms=NOW) == "NORMAL"
    assert process_concurrent_session(_df([]), now_ms=NOW) == "NORMAL"


def test_missing_columns_is_normal():
    df = pd.DataFrame({"event_time": [NOW]})
    assert process_concurrent_session(df, now_ms=NOW) == "NORMAL"


def test_two_distinct_ips_below_threshold_is_normal(monkeypatch):
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD", 3
    )
    monkeypatch.setattr(concurrent_session, "CONCURRENT_SESSION_PER_IP_THRESHOLD", 10)
    rows = [
        [NOW - 5 * MINUTE, "1.1.1.1"],
        [NOW - 2 * MINUTE, "2.2.2.2"],
    ]
    assert process_concurrent_session(_df(rows), now_ms=NOW) == "NORMAL"


def test_credential_sharing_distinct_ips_flags(monkeypatch):
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD", 3
    )
    monkeypatch.setattr(concurrent_session, "CONCURRENT_SESSION_PER_IP_THRESHOLD", 99)
    rows = [
        [NOW - 10 * MINUTE, "1.1.1.1"],
        [NOW - 5 * MINUTE, "2.2.2.2"],
        [NOW - 1 * MINUTE, "3.3.3.3"],
    ]
    assert process_concurrent_session(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_bot_sessions_per_ip_flags(monkeypatch):
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD", 99
    )
    monkeypatch.setattr(concurrent_session, "CONCURRENT_SESSION_PER_IP_THRESHOLD", 10)
    rows = [[NOW - i * MINUTE, "1.1.1.1"] for i in range(10)]
    assert process_concurrent_session(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_logins_outside_active_window_ignored(monkeypatch):
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_ACTIVE_WINDOW_MINUTES", 30
    )
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD", 3
    )
    monkeypatch.setattr(concurrent_session, "CONCURRENT_SESSION_PER_IP_THRESHOLD", 99)
    # Three distinct IPs but all older than the 30-minute active window.
    rows = [
        [NOW - 90 * MINUTE, "1.1.1.1"],
        [NOW - 70 * MINUTE, "2.2.2.2"],
        [NOW - 45 * MINUTE, "3.3.3.3"],
    ]
    assert process_concurrent_session(_df(rows), now_ms=NOW) == "NORMAL"


def test_now_ms_defaults_to_latest_event(monkeypatch):
    monkeypatch.setattr(
        concurrent_session, "CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD", 3
    )
    monkeypatch.setattr(concurrent_session, "CONCURRENT_SESSION_PER_IP_THRESHOLD", 99)
    rows = [
        [NOW - 8 * MINUTE, "1.1.1.1"],
        [NOW - 4 * MINUTE, "2.2.2.2"],
        [NOW, "3.3.3.3"],
    ]
    assert process_concurrent_session(_df(rows)) == "SUSPICIOUS"

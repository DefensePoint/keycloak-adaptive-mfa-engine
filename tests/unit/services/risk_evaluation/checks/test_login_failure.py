import pandas as pd
import pytest

from src.service.risk_evaluation.checks import login_failure
from src.service.risk_evaluation.checks.login_failure import process_login_failure

NOW = 1_700_000_000_000  # fixed reference time in ms
MINUTE = 60 * 1000


def _df(rows):
    return pd.DataFrame(rows, columns=["event_time", "ip_address"])


def test_empty_or_none_is_normal():
    assert process_login_failure(None, now_ms=NOW) == "NORMAL"
    assert process_login_failure(_df([]), now_ms=NOW) == "NORMAL"


def test_missing_event_time_column_is_normal():
    df = pd.DataFrame({"ip_address": ["1.1.1.1"]})
    assert process_login_failure(df, now_ms=NOW) == "NORMAL"


def test_few_irregular_failures_one_ip_is_normal(monkeypatch):
    # Keep every pattern's threshold out of reach: 3 spread-out failures, one IP.
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 5)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 3)
    rows = [
        [NOW - 40 * MINUTE, "1.1.1.1"],
        [NOW - 18 * MINUTE, "1.1.1.1"],
        [NOW - 2 * MINUTE, "1.1.1.1"],
    ]
    assert process_login_failure(_df(rows), now_ms=NOW) == "NORMAL"


def test_high_failure_rate_flags(monkeypatch):
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 5)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    # 5 failures within the window, single IP, irregular spacing.
    rows = [[NOW - m * MINUTE, "1.1.1.1"] for m in (50, 41, 33, 12, 1)]
    assert process_login_failure(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_distributed_brute_force_flags(monkeypatch):
    # Only distinct-IP pattern should fire: keep rate out of reach.
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 3)
    rows = [
        [NOW - 30 * MINUTE, "1.1.1.1"],
        [NOW - 15 * MINUTE, "2.2.2.2"],
        [NOW - 1 * MINUTE, "3.3.3.3"],
    ]
    assert process_login_failure(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_bot_like_regularity_flags(monkeypatch):
    # Isolate regularity: rate + distinct-IP unreachable.
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    # 6 perfectly evenly spaced failures (CV == 0) from a single IP.
    rows = [[NOW - m * MINUTE, "1.1.1.1"] for m in (25, 20, 15, 10, 5, 0)]
    assert process_login_failure(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_activity_burst_flags(monkeypatch):
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "REGULARITY_MIN_SAMPLES", 999)
    # 10 failures packed into ~9 seconds (well under the 60s burst window),
    # with jitter so the regularity pattern would not fire even if enabled.
    base = NOW - 30 * MINUTE
    jitter = [0, 800, 1700, 2400, 3300, 4100, 5200, 6000, 7100, 9000]
    rows = [[base + j, "1.1.1.1"] for j in jitter]
    assert process_login_failure(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_dos_cap_flags(monkeypatch):
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DOS_CAP", 50)
    rows = [[NOW - (i % 50) * 1000, "1.1.1.1"] for i in range(50)]
    assert process_login_failure(_df(rows), now_ms=NOW) == "SUSPICIOUS"


def test_failures_outside_window_are_ignored(monkeypatch):
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_WINDOW_MINUTES", 60)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 5)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    # 6 failures but all older than 60 minutes => none counted => NORMAL.
    rows = [[NOW - (90 + m) * MINUTE, "1.1.1.1"] for m in range(6)]
    assert process_login_failure(_df(rows), now_ms=NOW) == "NORMAL"


def test_now_ms_defaults_to_latest_event(monkeypatch):
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_RATE_THRESHOLD", 3)
    monkeypatch.setattr(login_failure, "LOGIN_FAILURE_DISTINCT_IP_THRESHOLD", 99)
    rows = [[NOW - m * MINUTE, "1.1.1.1"] for m in (8, 4, 0)]
    # No now_ms passed: reference is max(event_time); all three fall in window.
    assert process_login_failure(_df(rows)) == "SUSPICIOUS"

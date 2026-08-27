import pandas as pd

from src.service.risk_evaluation.checks.anonymous_detection import (
    process_anonymous_detection,
)


def test_anonymous_when_current_login_is_vpn():
    # History contains no VPN logins, but the CURRENT login is a VPN -> ANONYMOUS.
    df_user = pd.DataFrame({"is_vpn": [False, False]})
    current_event_dict = {"is_vpn": True}

    assert process_anonymous_detection(df_user, current_event_dict) == "ANONYMOUS"


def test_not_anonymous_when_current_login_not_vpn():
    df_user = pd.DataFrame({"is_vpn": [True, True]})
    current_event_dict = {"is_vpn": False}

    assert (
        process_anonymous_detection(df_user, current_event_dict) == "NOT ANONYMOUS"
    )


def test_uses_current_login_not_history():
    # Regression for the wrong-row bug: the result must reflect the CURRENT login,
    # never a stored row. Old code read df_user.iloc[-1]["is_vpn"] and would miss a
    # VPN current login whenever the most recent stored login was not a VPN.
    history_clean = pd.DataFrame({"is_vpn": [False, False, False]})
    assert process_anonymous_detection(history_clean, {"is_vpn": True}) == "ANONYMOUS"

    history_vpn = pd.DataFrame({"is_vpn": [True, True, True]})
    assert (
        process_anonymous_detection(history_vpn, {"is_vpn": False}) == "NOT ANONYMOUS"
    )


def test_missing_is_vpn_defaults_to_not_anonymous():
    assert process_anonymous_detection(pd.DataFrame(), {}) == "NOT ANONYMOUS"

import pandas as pd


def process_anonymous_detection(
    df_user: pd.DataFrame, current_event_dict: dict
) -> str:
    """Determine whether the CURRENT login attempt is anonymous (VPN/proxy).

    The VPN/proxy status is computed for the in-flight login during the decision
    request and carried in ``current_event_dict["is_vpn"]``. The stored history
    (``df_user``) is intentionally not consulted: this check is about the login the
    user is attempting now, which is not yet persisted in the event history. Reading
    ``df_user`` here would evaluate a *previous* login's VPN status instead.

    Args:
        df_user (pd.DataFrame):
            Stored login history. Unused by the logic; kept for signature
            consistency with the other risk checks.
        current_event_dict (dict):
            The in-flight login event. Expected to contain an ``is_vpn`` flag.

    Returns:
        str: "ANONYMOUS" if the current login is via VPN/proxy, otherwise
        "NOT ANONYMOUS".
    """
    is_vpn = bool(current_event_dict.get("is_vpn", False))

    return "ANONYMOUS" if is_vpn else "NOT ANONYMOUS"

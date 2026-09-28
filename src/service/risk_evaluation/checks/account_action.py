import logging


def process_account_action(recent_action_count: int) -> str:
    """Classify whether the user recently made a sensitive account change.

    A login shortly after a password change/reset, an MFA credential being
    added or removed, or an email change is the classic account-takeover
    pattern (attacker changes credentials, then signs in). Any such action
    inside the configured window flags the login as SUSPICIOUS so the scoring
    layer treats it as a risk-raising signal.

    Note this is a proportional *hint*, not proof: legitimate users change
    passwords too. It is one weighted signal among many, so it raises risk
    (and combines with unfamiliar-device / new-network signals) rather than
    hard-blocking on its own.

    Args:
        recent_action_count:
            Number of sensitive account-action events for the user within the
            window (counted by the caller from the engine's event cache).

    Returns:
        str: "SUSPICIOUS" if at least one sensitive action occurred in the
        window, otherwise "NORMAL".
    """
    if recent_action_count >= 1:
        logging.info(
            "Account-action analysis: %d sensitive account change(s) in window "
            "=> SUSPICIOUS",
            recent_action_count,
        )
        return "SUSPICIOUS"

    logging.debug("Account-action analysis: no recent sensitive changes => NORMAL")
    return "NORMAL"

"""Human-readable phrasing for risk-decision explanations.

The engine's risk logic uses terse internal parameter/flag names. This module
turns them into plain-English fragments so the ``[RISK WHY]`` debug log reads
like an explanation a person can follow. It has no logic of its own: callers in
``decision.py`` decide *what* happened; this module only decides *how to say it*.
"""

# Internal signal/parameter name -> plain-English label.
FRIENDLY_LABELS = {
    "client": "the application being signed in to",
    "ip_address": "network / IP address",
    "device": "device",
    "operating_system": "operating system",
    "browser": "browser",
    "system_language": "browser language",
    "screen_resolution": "screen size",
    "geolocation_cluster_label": "usual sign-in location pattern",
    "event_cluster_label": "usual device/behaviour pattern",
    "geolocation": "geographic location",
    "date_time": "time of day",
    "time_interval": "time-between-logins pattern",
    "impossible_travel": "impossible travel between logins",
    "anonymous_detection": "anonymised network (VPN/proxy/Tor)",
    "vpn": "VPN / proxy use",
    "inactive_account": "long-dormant account",
    "login_failure": "recent failed-login pattern",
    "concurrent_session": "concurrent active sessions",
    "recent_account_change": "recent password/credential change",
    "__credibility": "device / network familiarity",
}


def friendly(name: str) -> str:
    """Return a plain-English label for an internal signal name."""
    if name in FRIENDLY_LABELS:
        return FRIENDLY_LABELS[name]
    # Fallback: humanise an unknown key (e.g. "some_new_flag" -> "some new flag").
    return name.replace("_", " ").strip()


def friendly_list(names) -> str:
    """Join names into a readable clause: 'a', 'a and b', 'a, b and c'."""
    labels = [friendly(n) for n in names if n]
    if not labels:
        return "nothing"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


def describe_contributions(contributions: dict, limit: int = 4):
    """Split Log-Odds contributions into risk-raising and trust-lowering signals.

    Args:
        contributions: signal name -> evidence value (positive raises risk,
            negative lowers it), as produced by ``LogOddsScorer``.
        limit: how many of each to name (largest magnitude first).

    Returns:
        (risk_phrase, trust_phrase): two human-readable clauses, or "" when a
        side has no meaningful contributors.
    """
    risk = sorted(
        ((k, v) for k, v in contributions.items() if v > 0.01),
        key=lambda kv: kv[1],
        reverse=True,
    )
    trust = sorted(
        ((k, v) for k, v in contributions.items() if v < -0.01),
        key=lambda kv: kv[1],
    )
    risk_phrase = friendly_list([k for k, _ in risk[:limit]]) if risk else ""
    trust_phrase = friendly_list([k for k, _ in trust[:limit]]) if trust else ""
    return risk_phrase, trust_phrase

"""The matrix rows, as data.

A row is a delta from the baseline context plus optional seeding, so adding one is a
dict rather than a function.

Two things are deliberately absent from `expect`.

Most rows do not hardcode a level. The level depends on the device and network
familiarity value, which moves with how much of the seeded history matches, so
hardcoding it would either be wrong or would pin an incidental number. Those rows are
instead checked two ways: the arithmetic is verified against whatever the engine says
changed (see `expected_band`), and the level itself is compared against the recorded
baseline, which is what catches drift.

Rows where a documented rule fixes the answer regardless of score do hardcode it: a
deny-list match, a hazard escalation, and the history gate.
"""

from tests.e2e.matrix_env import MATRIX_WEIGHTS

# Verified against the bundled databases. Asserted during setup, because DB-IP Lite
# refreshes monthly and an address can be reassigned: a moved country would otherwise
# surface as a wrong risk level rather than as stale data.
IP_PALETTE = {
    "203.0.113.50": {"country": "", "note": "baseline is non-public, no country"},
    "212.51.144.1": {"country": "CH", "note": "clean routable, Zurich"},
    "212.51.144.9": {"country": "CH", "note": "clean, same city as baseline"},
    "62.2.0.1": {"country": "CH", "note": "clean, different city, same country"},
    "193.99.144.80": {"country": "DE", "note": "clean, different country"},
    "1.201.0.1": {"country": "KR", "note": "on the country deny list"},
    "203.0.113.9": {"country": "", "note": "on the ip deny list, non-public"},
    "203.0.113.7": {"country": "", "note": "on the ip allow list, non-public"},
    "171.25.193.25": {"country": "SE", "note": "real Tor exit"},
    "8.8.8.8": {"country": "US", "note": "hosting, datacenter label"},
}

UA_MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
UA_MAC_FIREFOX = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0"
)
UA_WIN_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

# Signals the engine names in its explanation, mapped back to the parameter whose
# weight they carry. The arithmetic check has to translate "usual device/behaviour
# pattern" back to event_cluster_label.
#
# Copied from risk_evaluation/explain.py FRIENDLY_LABELS, and asserted against it at
# import time so a renamed label breaks here loudly rather than silently dropping a
# signal from every sum. Signals absent from that map fall through the engine's
# humanising fallback, which turns country_name into "country name".
SIGNAL_BY_LABEL = {
    "the application being signed in to": "client",
    "network / IP address": "ip_address",
    "device": "device",
    "operating system": "operating_system",
    "browser": "browser",
    "browser language": "system_language",
    "screen size": "screen_resolution",
    "usual sign-in location pattern": "geolocation_cluster_label",
    "usual device/behaviour pattern": "event_cluster_label",
    "time of day": "date_time",
    "time-between-logins pattern": "time_interval",
    "impossible travel between logins": "impossible_travel",
    "anonymised network (VPN/proxy/Tor)": "anonymous_detection",
    "long-dormant account": "inactive_account",
    "recent failed-login pattern": "login_failure",
    "concurrent active sessions": "concurrent_session",
    "recent password/credential change": "recent_account_change",
    "country name": "country_name",
}


# Bands from WEIGHT_RISK_BANDS (3, 6): below 3 is Risk 1, 3 to 5 is Risk 2, 6 or more
# is Risk 3. Asserted per row against whatever the engine reported as changed, so the
# scoring arithmetic is checked even on rows whose final level is not hardcoded.
WEIGHT_BANDS = (3, 6)


def expected_band(changed_signals: list[str]) -> int:
    """The level the weight bands imply for this set of changed signals."""
    total = sum(MATRIX_WEIGHTS.get(s, 0) for s in changed_signals)
    if total < WEIGHT_BANDS[0]:
        return 1
    if total < WEIGHT_BANDS[1]:
        return 2
    return 3


def signals_from_why(why: str) -> list[str]:
    """Parameter names for the signals the engine said differed.

    Parsed from the explanation rather than inferred from the delta, because the point
    of the arithmetic check is to use the engine's own account of what changed.

    The list is split into items and matched whole. Substring matching would be wrong
    in both directions: "device" appears inside "usual device/behaviour pattern", and
    "browser" inside "browser language", so a single changed cluster would be counted
    as a changed device too and the sums would silently inflate.
    """
    if "differ from this user's norm:" not in why:
        return []
    listed = why.split("differ from this user's norm:", 1)[1]
    listed = listed.split("|")[0].strip().rstrip(".")

    items = []
    for chunk in listed.split(","):
        for part in chunk.split(" and "):
            part = part.strip()
            if part:
                items.append(part)

    found = []
    unknown = []
    for item in items:
        if item in SIGNAL_BY_LABEL:
            found.append(SIGNAL_BY_LABEL[item])
        else:
            unknown.append(item)
    if unknown:
        # Loud rather than silent: an unmapped label would drop weight from the sum
        # and make the arithmetic check pass for the wrong reason.
        raise AssertionError(
            f"unmapped signal label(s) {unknown!r} in explanation; update "
            f"SIGNAL_BY_LABEL from risk_evaluation/explain.py"
        )
    return found


# --- the rows --------------------------------------------------------------
#
# delta           overrides on BASELINE_CONTEXT
# seed            keyword arguments to the profile clone (hour_shift, days_ago_of_oldest)
# expect          a level, only where a documented rule fixes it regardless of score
# expect_signals  signals that must appear in what the engine reports as changed
# gate            True to skip cloning, leaving the user untrained
# choreograph     (name, args) for the three signals a single login cannot express

ROWS = [
    # -- baseline ----------------------------------------------------------
    {
        "id": "B00", "delta": {}, "expect": 1,
        "note": "trained user, nothing changed. Every other row is measured from here",
    },

    # -- one signal at a time ---------------------------------------------
    # Most of these also trip event_cluster_label, weight 3, because it clusters the
    # whole context vector and any field moving changes the cluster. That is real
    # behaviour rather than a harness artefact, so the rows are honest delta sets and
    # the arithmetic check uses whatever actually fired.
    {
        "id": "S01", "delta": {"user_agent": UA_MAC_FIREFOX},
        "note": "browser, weight 1",
    },
    {
        "id": "S02", "delta": {"user_agent": UA_WIN_CHROME},
        "note": "device and operating system, weight 2 each",
    },
    {
        "id": "S03", "delta": {"screen_res": "1024x768"},
        "note": "screen resolution, weight 1",
    },
    {
        "id": "S04", "delta": {"accept_language": "fr-FR,fr;q=0.9"},
        "note": "system language, weight 2",
    },
    {
        "id": "S05", "delta": {"xff": "212.51.144.9"},
        "note": "ip address only, same city so geo is unchanged",
    },
    {
        "id": "S06", "delta": {"xff": "62.2.0.1"},
        "note": "ip address, different city in the same country",
    },
    {
        "id": "S07", "delta": {"xff": "193.99.144.80"},
        "note": "ip address and country, CH to DE",
    },
    {
        "id": "S08", "delta": {"xff": "8.8.8.8"},
        "note": "hosting address: datacenter label, is_vpn stays false by default",
    },
    {
        "id": "S09", "delta": {}, "seed": {"hour_shift": 7},
        "note": "time of day, weight 3. The only clean single-signal row: shifting "
                "history changes no context field, so the cluster does not move",
    },
    {
        "id": "S10", "delta": {}, "seed": {"days_ago_of_oldest": 70},
        "note": "dormant account: history older than the 40 day threshold",
    },

    # -- the anonymiser signal --------------------------------------------
    {
        "id": "A01", "delta": {"xff": "171.25.193.25"}, "expect": 3,
        "note": "real Tor exit. Five signals move, one short of the hazard threshold "
                "of 6, so this reaches Risk 3 by weight rather than by escalation",
    },
    {
        "id": "A02", "delta": {"xff": "171.25.193.25"}, "seed": {"hour_shift": 7},
        "expect": 3,
        "note": "the takeover shape: Tor plus an unusual hour is 6 signals, which "
                "trips hazard, with every device field left identical. Measured, no "
                "familiarity adjustment follows, so the hazard floor is not exercised "
                "here either; see the known limits in signal-matrix-plan.md",
    },

    # -- hard overrides ----------------------------------------------------
    {
        "id": "D01", "delta": {"xff": "203.0.113.9"}, "expect": 4,
        "note": "ip address on the deny list. A hard override to the rejection level, "
                "regardless of score or familiarity",
    },
    {
        "id": "D02", "delta": {"xff": "1.201.0.1"}, "expect": 4,
        "note": "country KR on the deny list",
    },
    {
        "id": "W01", "delta": {"xff": "203.0.113.7"},
        "note": "ip address on the allow list: caps the level at 2 rather than "
                "forcing anything",
    },

    # -- hazard ------------------------------------------------------------
    {
        "id": "H01",
        "delta": {"user_agent": UA_WIN_CHROME, "screen_res": "800x600",
                  "accept_language": "ja-JP,ja;q=0.9", "xff": "193.99.144.80"},
        "seed": {"hour_shift": 7}, "expect": 3,
        "note": "many signals at once. Hazard forces Risk 3 and holds it against a "
                "familiar device",
    },

    # -- the three sequence signals ---------------------------------------
    # These cannot be expressed as a delta, because they are properties of a sequence
    # rather than of one login. The level is not asserted: it depends on the
    # familiarity value like the other unpinned rows, and the baseline covers it.
    # What is asserted is that the signal fired at all, which is the point of the row.
    {
        "id": "F01", "delta": {}, "choreograph": ("login_failure", ()),
        "expect_signals": ["login_failure"],
        "note": "failed step-ups, enough to trip the failure-rate pattern",
        # Kept as an executable record of a gap rather than deleted, and strict, so
        # that whoever fixes the wiring is told to remove this mark instead of
        # discovering the row had been quietly skipped for months.
        "unreachable":
            "login_failure reads auth_process rows with final_status=LOGIN_ERROR, and "
            "neither failure a user can produce creates one. A wrong password does "
            "emit Keycloak's LOGIN_ERROR event, but the adaptive authenticator runs "
            "after the password form, so no auth process is open and "
            "AuthEventService.__finalize_process discards it: measured, 45 such events "
            "all with a null auth_process, and zero auth_process rows. A wrong emailed "
            "code happens inside an open process, but Keycloak emits no event for it "
            "at all: measured, zero auth_event rows for a user who failed five. So the "
            "signal cannot fire from real behaviour, and the four patterns it "
            "implements (failure rate, distributed brute force, burst, bot regularity) "
            "cannot see password guessing, which is what they describe. See the known "
            "limits in signal-matrix-plan.md.",
    },
    {
        "id": "C01", "delta": {},
        "choreograph": ("concurrent_session", (["212.51.144.9", "62.2.0.1"],)),
        "expect_signals": ["concurrent_session"],
        "note": "sessions from two other addresses, plus this login's own, reaching "
                "the distinct-address threshold the engine reads as credential sharing",
    },
    {
        "id": "E01", "delta": {}, "choreograph": ("recent_account_change", ()),
        "expect_signals": ["recent_account_change"],
        "note": "the user changes their own password, then signs in. User-initiated "
                "because an admin reset is deliberately not forwarded to the engine",
    },

    # -- the history gate --------------------------------------------------
    {
        "id": "G01", "delta": {}, "gate": True, "expect": 3,
        "note": "untrained user: the gate short-circuits to a cautious level before "
                "any signal is weighed",
    },
    {
        "id": "G02", "delta": {"user_agent": UA_WIN_CHROME, "xff": "193.99.144.80"},
        "gate": True, "expect": 3,
        "note": "untrained and several signals changed: still the gate, proving it "
                "runs before scoring",
    },
    {
        "id": "G03", "delta": {"xff": "203.0.113.9"}, "gate": True, "expect": 4,
        "note": "untrained plus a denied address: the deny list still escalates",
    },
]


def row_ids() -> list[str]:
    return [r["id"] for r in ROWS]

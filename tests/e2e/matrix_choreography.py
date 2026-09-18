"""Setting up the three signals that a single login cannot express.

Sixteen of the nineteen signals are properties of one login, so a row states them as a
delta and sends it. Three are properties of a *sequence*, and cannot be driven that
way at all:

    login_failure          failures have to have happened, and recently
    concurrent_session     several sessions have to be active at once
    recent_account_change  the account has to have been changed, then signed into

Each function here performs that sequence and returns what `run_row` needs to know,
including the facts it established, so the artifact records what the choreography
actually achieved rather than what it intended.

Two of the three work. `login_failure` turned out not to be reachable from any
failure a real user can produce, so its row is a strict xfail carrying the measurement;
`deliberate_failures` below documents why in full.

**Real actions, not seeded rows.** The profile clone rewrites history in SQL because
training 20 users through the browser would take half an hour. These do not use it: the
sessions are real completed logins and the password change is a real user-submitted
form. The whole point of these rows is the path from a Keycloak event, through the SPI
webhook, to what the engine stores and then reads back, and seeding the destination
would skip exactly the part under test. They cost a few seconds each, which is
affordable for three rows.

**Each verifies its own setup.** A sequence that did not take effect fails as "the
setup did not happen", naming what was missing, rather than surfacing later as a
puzzling risk level on a row that looks like a product defect.

**The thresholds are read, not copied.** Each function asks the engine for the
threshold it has to cross rather than hardcoding a number that would silently stop
crossing it if the deployment changed. `preflight` already refuses to run when those
values differ from the baseline's fingerprint.
"""

import time

from tests.e2e.matrix_lib import (
    BASELINE_CONTEXT,
    _admin,
    login,
    psql,
)

# The password the account is left on after the update-password choreography. Must
# differ from the one the account was created with: Keycloak rejects an update that
# reuses the current password, and the row login would then be using one never set.
CHANGED_PASSWORD = "Ch4ngedPassw0rd!"


class ChoreographyError(RuntimeError):
    """The sequence a row depends on did not happen, so the row cannot mean anything."""


def _engine_setting(name: str) -> int:
    from tests.e2e.matrix_env import engine_setting

    return engine_setting(name)


# --- login_failure ---------------------------------------------------------


def deliberate_failures(step_up_ip: str = "193.99.144.80"):
    """Fail enough step-ups to trip the failure-rate pattern.

    Step-ups, not passwords, and that distinction is the whole reason this function
    reads the way it does.

    `login_failure` scores `auth_process` rows whose `final_status` is `LOGIN_ERROR`.
    Those rows are only ever produced by `AuthEventService.__finalize_process`, which
    runs on a LOGIN_ERROR event *only if an auth process is already open* for the
    user. The process is opened by the adaptive authenticator, and in this realm's
    flow that runs after the password form. So a rejected password arrives when
    nothing is open, and finalises nothing.

    Measured, not inferred: five logins with a wrong password produced 45 LOGIN_ERROR
    rows in `auth_event`, every one of them with a null `auth_process`, and zero rows
    in `auth_process`. See the known limits in signal-matrix-plan.md, because it means
    the patterns this check implements cannot see password guessing at all.

    What is reachable is a failure *after* risk evaluation: a login from an unfamiliar
    address is asked for an emailed code, and a wrong code finalises the open process
    as LOGIN_ERROR. That is what this drives, so the signal is covered end to end even
    though the failures it can see are not the ones its own docstring describes.

    The rate pattern is targeted rather than the other three the check offers.
    Distributed brute force would need three source addresses and would also move the
    ip_address signal; burst and bot-regularity depend on timing this cannot control
    from outside. A count is reproducible, so the count is what this uses.
    """

    def run(token, username, user_id):
        needed = _engine_setting("LOGIN_FAILURE_RATE_THRESHOLD")

        for attempt in range(needed):
            outcome = login(
                {**BASELINE_CONTEXT, "xff": step_up_ip}, username, bad_code=True
            )
            if outcome.ok:
                raise ChoreographyError(
                    f"attempt {attempt + 1} completed despite a deliberately wrong "
                    f"code, so this row is not producing failures at all"
                )
            if "email-otp-wrong" not in outcome.steps:
                raise ChoreographyError(
                    f"attempt {attempt + 1} never reached a step-up, so there was no "
                    f"open auth process to fail. A LOGIN_ERROR outside an open "
                    f"process is not recorded as one. Steps: {outcome.steps}, "
                    f"detail: {outcome.detail}"
                )

        # The webhook is asynchronous, so the rows may not have landed yet. Waiting on
        # the count rather than sleeping a fixed time keeps this from being flaky on a
        # slow machine and fast when it is not.
        recorded = _await_failure_rows(user_id, needed)
        if recorded < needed:
            raise ChoreographyError(
                f"only {recorded} of {needed} failed step-ups became LOGIN_ERROR rows "
                f"in auth_process, so the login_failure signal cannot fire. Check that "
                f"the engine is finalising processes on LOGIN_ERROR events."
            )

        return {"facts": {
            "failed_step_ups_recorded": recorded,
            "threshold": needed,
            "failure_kind": "wrong emailed code (a wrong password is not recorded)",
        }}

    return run


def _await_failure_rows(user_id: str, needed: int, timeout_s: float = 20.0) -> int:
    deadline = time.time() + timeout_s
    seen = 0
    while time.time() < deadline:
        raw = psql(
            f"select count(*) from auth_process where user_id='{user_id}' "
            f"and final_status='LOGIN_ERROR';"
        )
        try:
            seen = int(raw.strip().splitlines()[0])
        except (ValueError, IndexError):
            seen = 0
        if seen >= needed:
            return seen
        time.sleep(0.5)
    return seen


# --- concurrent_session ----------------------------------------------------


def overlapping_sessions(extra_ips: list[str]):
    """Establish sessions from several addresses at once.

    The engine approximates active sessions with successful logins inside the active
    window, because it does not own Keycloak's session store. The credential-sharing
    pattern needs at least `CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD` distinct
    addresses among them, counting the row's own login, so this logs in from the
    addresses given and the row supplies the last one.

    The per-IP pattern is the alternative and is not used: it needs ten logins from
    one address, which is five times the work for the same boolean.

    Note this row also trips impossible_travel and time_interval, because logging in
    from two cities within a few seconds is exactly that, and the gaps between those
    logins are nothing like the seeded history. That is real behaviour rather than an
    artefact, the arithmetic check validates whatever fired, and it makes this the only
    row that covers impossible_travel at all.
    """

    def run(token, username, user_id):
        needed = _engine_setting("CONCURRENT_SESSION_DISTINCT_IP_THRESHOLD")
        # The row's own login contributes the address the engine counts last.
        if len(extra_ips) + 1 < needed:
            raise ChoreographyError(
                f"this row logs in from {len(extra_ips)} address(es) plus its own, "
                f"which is under the {needed} the engine needs to call it concurrent"
            )

        established = []
        for ip in extra_ips:
            outcome = login({**BASELINE_CONTEXT, "xff": ip}, username)
            if not outcome.ok:
                raise ChoreographyError(
                    f"could not establish a session from {ip}: {outcome.detail} "
                    f"(steps: {outcome.steps}). Without it there are too few "
                    f"addresses for the signal to fire."
                )
            established.append(ip)

        return {"facts": {
            "sessions_from": established,
            "distinct_ips_including_row": len(established) + 1,
            "threshold": needed,
        }}

    return run


# --- recent_account_change -------------------------------------------------


def user_changed_password():
    """Have the user change their own password, then sign in.

    User-initiated deliberately. The SPI forwards Keycloak's credential-change event
    to the engine, which caches it and counts it on the next login. Observed, the event
    for a password update on Keycloak 26 is UPDATE_CREDENTIAL rather than the older
    UPDATE_PASSWORD; both are in the SPI's forwarded set and in the engine's
    ACCOUNT_ACTION_EVENT_TYPES, so this does not depend on which one arrives, and the
    recorded fact in the artifact names the one that did. An *admin* password reset
    does not work: `AmfaWebhookEventListenerProvider.onEvent(AdminEvent, ..)` is
    an empty method, on the stated grounds that AMFA only cares about end-user
    authentication events, and the realm has `adminEventsEnabled: false` besides.
    Verified by resetting a password through the admin API and finding no cache entry.

    So the change is driven the way a user would experience it: the UPDATE_PASSWORD
    required action is set, and the next login is presented with the form and fills
    it. That leaves the account on a new password, which is returned so the row's own
    login uses it.
    """

    def run(token, username, user_id):
        _admin(
            "PUT", f"/users/{user_id}", token,
            json={"requiredActions": ["UPDATE_PASSWORD"]},
        ).raise_for_status()

        outcome = login(
            BASELINE_CONTEXT, username, new_password=CHANGED_PASSWORD
        )
        if "update-password" not in outcome.steps:
            raise ChoreographyError(
                f"the login was never asked to change the password, so no "
                f"UPDATE_PASSWORD event happened. Steps: {outcome.steps}, "
                f"detail: {outcome.detail}"
            )

        cached = _await_cached_action(user_id)
        if not cached:
            raise ChoreographyError(
                "the password change did not reach the engine's cache, so "
                "recent_account_change cannot fire. Check that the realm has the "
                "amfa-webhook event listener enabled and the adaptive-auth toggle set."
            )

        return {"password": CHANGED_PASSWORD, "facts": {"cached_event": cached}}

    return run


def _await_cached_action(user_id: str, timeout_s: float = 20.0) -> str | None:
    """The cache key the webhook wrote for this user, once it appears.

    Read through redis-cli rather than a client library, so this needs nothing the
    suite does not already have. The bucket prefix is the engine's own: 'd' for a
    window of a day or less, which is the shipped 1440 minutes.
    """
    import subprocess

    from tests.e2e.e2e_common import DOCKER_REDIS

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = subprocess.run(
            ["docker", "exec", DOCKER_REDIS, "redis-cli", "--scan",
             "--pattern", f"d:*:{user_id}:*"],
            capture_output=True, text=True, timeout=30,
        )
        keys = [k for k in out.stdout.strip().splitlines() if k]
        if keys:
            return keys[0]
        time.sleep(0.5)
    return None


# The rows reference these by name, so a row stays data rather than becoming code.
BY_NAME = {
    "login_failure": deliberate_failures,
    "concurrent_session": overlapping_sessions,
    "recent_account_change": user_changed_password,
}

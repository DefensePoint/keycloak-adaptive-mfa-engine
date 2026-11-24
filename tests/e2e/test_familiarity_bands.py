"""The familiarity adjustment, and that a real login reaches every branch of it.

The K family of tests/e2e/coverage-plan.md.

After scoring, the engine nudges the level by how familiar the device and network are:

    c = device_credibility * 0.55 + network_credibility * 0.45

    network < 0.30 or c < 0.30   unfamiliar   raise to Risk 3
    network < 0.60 or c < 0.60   somewhat     leave the score alone
    otherwise                    familiar     lower by one step

The network is judged on its own as well, because a familiar device alone reaches
0.64 and must not vouch for an address, country or anonymiser the user has never
used. Familiarity lowers only a level scored from changed signals, since a clean
login was already relaxed one step by the drop-down, and never one raised by a
signal about the account: a concurrent session, impossible travel or a recent
credential change.

`tests/unit/services/test_familiarity_rule.py` covers the rule as pure functions.
This file asks a different question: which of its branches a login can actually reach.

Until the device fingerprint was computed the same way before and after the history
gate, only the raise and the no-change branch could. The first logins of a user stored
the hash of the raw screen size and later logins looked up the hash of the size rounded
to its common bucket, so on a screen that is not exactly a common one, which this
suite's 1728x1117 is not, device credibility stayed at its 0.2 prior and c could not
pass 0.56. K03, K04 and K07 now hold the lowering branch and the device half of the
history to account.
"""

import re

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# The boundaries in `_adjust_for_credibility`, named so a failure message can say which
# band it expected rather than quoting a number.
UNFAMILIAR_BELOW = 0.30
NO_CHANGE_BELOW = 0.60

FAMILIARITY = re.compile(r"familiarity ([0-9.]+)")



def reported_familiarity(why: str) -> float | None:
    found = FAMILIARITY.search(why)
    return float(found.group(1)) if found else None


def run_in(realm_run, row_id: str, delta: dict, **kwargs) -> dict:
    """One row, with the credibility the engine computed attached to the result.

    The engine only names familiarity in its explanation when the adjustment moves
    the level, so the middle band is silent. The two values are read from its debug
    log instead, which reports them on every login.
    """
    original = lib.REALM
    lib.REALM = realm_run["run"].realm
    try:
        mark = lib.log_mark()
        result = lib.run_row(
            realm_run["token"], realm_run["golden_id"], row_id, delta, **kwargs
        )
        realm_run["run"].track(result["user_id"])
        measured = lib.credibility_since(mark)
        result["device_credibility"], result["network_credibility"] = (
            measured if measured else (None, None)
        )
        result["familiarity"] = (
            None if not measured else measured[0] * 0.55 + measured[1] * 0.45
        )
        return result
    finally:
        lib.REALM = original


@pytest.fixture(scope="module")
def realm():
    with env.MatrixRun() as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)
            target = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
            lib.train(lib.BASELINE_CONTEXT, username, golden_id, target=target)
            if lib.completed_logins(golden_id) < target:
                pytest.fail("could not train the golden profile past the history gate")
            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original


# --- K01, K02: the two reachable bands ------------------------------------


def test_an_unfamiliar_network_raises_the_level(realm):
    """K01. A known device on an address the user has never used is raised to Risk 3.

    The device is familiar, so the combined value is 0.64, but a familiar device does
    not vouch for a new network: the network half alone is at its 0.2 prior, and that
    raises the level as a fully unfamiliar context would.
    """
    result = run_in(realm, "K01", {"xff": "62.2.0.1"})

    network = result["network_credibility"]
    assert network is not None, "the engine logged no credibility for this login"
    assert network < UNFAMILIAR_BELOW, (
        f"a login from an unused address computed network credibility {network}, "
        f"expected its prior.\n  why: {result['why']}"
    )
    assert "raising" in result["why"], (
        f"the network is new ({network}) but the level was not raised.\n"
        f"  why: {result['why']}"
    )
    assert result["risk"] == 3, (
        f"a new network should force Risk 3, got {result['risk']}.\n  why: {result['why']}"
    )


def test_a_familiar_network_leaves_the_score_alone(realm):
    """K02. The `0.3 <= c < 0.6` branch, and the other side of the K01 boundary.

    A login from the user's usual address on a screen they have not used: the network
    is familiar and the device is not, which lands between the raise and the lowering
    bands.
    """
    result = run_in(realm, "K02", {"screen_res": "1024x768"})

    familiarity = result["familiarity"]
    assert familiarity is not None, "the engine logged no credibility for this login"
    assert UNFAMILIAR_BELOW <= familiarity < NO_CHANGE_BELOW, (
        f"a login from the usual address computed familiarity {familiarity:.2f}, "
        f"expected the no-change band.\n  why: {result['why']}"
    )
    # The band is silent by design: nothing is said because nothing was changed.
    assert "familiarity" not in result["why"], (
        f"familiarity {familiarity:.2f} is in the no-change band but the engine "
        f"reported an adjustment.\n  why: {result['why']}"
    )


# --- K06: the allowlist escape hatch --------------------------------------


def test_an_allowlisted_attribute_suppresses_the_unfamiliar_raise(realm):
    """K06. An allowlisted login is not punished for being unfamiliar.

    The adjustment skips its raise when a whitelisted attribute matched, which is the
    point of an allow list: a known-good address should not be escalated merely for
    being new to this user.
    """
    allowlisted = run_in(realm, "K06", {"xff": "203.0.113.7"})
    unlisted = run_in(realm, "K06b", {"xff": "62.2.0.1"})

    assert unlisted["risk"] == 3, (
        f"the control login was not raised, so this proves nothing: "
        f"{unlisted['why']}"
    )
    assert allowlisted["risk"] < 3, (
        f"an allowlisted address was still raised to Risk {allowlisted['risk']} for "
        f"being unfamiliar.\n  why: {allowlisted['why']}"
    )


# --- K03, K04: the lowering branch ---------------------------------------


@pytest.fixture(scope="module")
def interval_realm():
    """A realm where a login seconds after the last ones scores Risk 2 on its own.

    The only changed signal that leaves both the device and the network familiar,
    and is not about the account, is the time between logins. It carries weight 1 in
    the matrix, too little to move the level, so here it carries the weight of the
    Risk 2 band, and the cluster signal is off so that nothing else fires with it.
    """
    with env.MatrixRun(overrides={
        "disabled": {"event_cluster_label"},
        "weights": {"time_interval": 3},
    }) as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)
            target = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
            lib.train(lib.BASELINE_CONTEXT, username, golden_id, target=target)
            if lib.completed_logins(golden_id) < target:
                pytest.fail("could not train the golden profile past the history gate")
            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original


def _two_logins_moments_ago(token, username, user_id):
    """Two logins seconds apart, as X04 places them; one leaves the median a day."""
    for attempt in range(2):
        outcome = lib.login(lib.BASELINE_CONTEXT, username)
        if not outcome.ok:
            raise AssertionError(f"could not place prior login {attempt + 1}: {outcome.detail}")
    return {"facts": {"prior_logins": 2, "spacing": "seconds"}}


def test_a_familiar_login_lowers_a_scored_level(interval_realm):
    """K03. A returning user on a known device and network is recognised.

    The login changes one signal that says nothing about the device, the network or
    the account, which scores Risk 2. Familiarity takes it down one step, so the
    returning user is not challenged for logging in again moments later. That the
    step is one and never more is held by the unit tests and by K04.
    """
    result = run_in(interval_realm, "K03", {}, before=_two_logins_moments_ago)

    familiarity = result["familiarity"]
    assert familiarity is not None, "the engine logged no credibility for this login"
    assert familiarity >= NO_CHANGE_BELOW and result["network_credibility"] >= NO_CHANGE_BELOW, (
        f"the user's own device and address computed familiarity {familiarity:.2f} "
        f"(device {result['device_credibility']}, network "
        f"{result['network_credibility']}), below the {NO_CHANGE_BELOW} that lowers.\n"
        f"  why: {result['why']}"
    )
    assert "time-between-logins pattern" in result["why"] and "tentative Risk 2" in result["why"], (
        f"the login did not score Risk 2 from the interval, so this proves nothing.\n"
        f"  why: {result['why']}"
    )
    assert "lowering from Risk 2 to Risk 1" in result["why"], (
        f"a familiar login was not lowered by familiarity.\n  why: {result['why']}"
    )
    assert result["risk"] == 1, (
        f"familiarity should lower one step, to Risk 1; got Risk {result['risk']}.\n"
        f"  why: {result['why']}"
    )


def test_a_clean_familiar_login_is_relaxed_once_not_twice(realm):
    """K04. Nothing changed, after a Risk 3 decision.

    The drop-down relaxes a clean login one step below the last decision. Familiarity
    must not take a second step on top of it, which would turn one cautious decision
    into no challenge at all.
    """
    result = run_in(realm, "K04", {}, prior_decision=3)

    familiarity = result["familiarity"]
    assert familiarity is not None, "the engine logged no credibility for this login"
    assert familiarity >= NO_CHANGE_BELOW, (
        f"the most familiar login available computed familiarity {familiarity:.2f}, "
        f"so this proves nothing.\n  why: {result['why']}"
    )
    assert result["risk"] == 2, (
        f"a clean login after Risk 3 should be relaxed once, to Risk 2; got Risk "
        f"{result['risk']}.\n  why: {result['why']}"
    )
    assert "familiarity" not in result["why"], (
        f"familiarity moved a clean login that the drop-down had already relaxed.\n"
        f"  why: {result['why']}"
    )


def test_device_credibility_counts_its_history(realm):
    """K07. The device half of familiarity reads the same history as the network half.

    The login's history rows carry its own device and network, so both halves are
    computed from the same successes. Before the fix the device half found none of
    them and stayed at its 0.2 prior while the network half reached 1.0: the first
    logins stored the hash of the raw screen size, and this one looked up the hash
    of the rounded size.
    """
    result = run_in(realm, "K07", {})

    device = result["device_credibility"]
    network = result["network_credibility"]
    assert device is not None, "the engine logged no credibility for this login"
    assert device > 0.2, (
        f"device credibility is {device}, its prior: the login's own device was not "
        f"found in its history, so a stored hash and the looked-up one differ."
    )
    assert device == pytest.approx(network, abs=0.001), (
        f"the device half computed {device} and the network half {network} from the "
        f"same history rows; they should agree."
    )

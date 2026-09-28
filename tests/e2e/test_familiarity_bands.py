"""The familiarity adjustment, and how much of it a real login can reach.

The K family of tests/e2e/coverage-plan.md.

After scoring, the engine nudges the level by how familiar the device and network are:

    c = device_credibility * 0.55 + network_credibility * 0.45

    c < 0.30   unfamiliar        raise to Risk 3
    c < 0.60   somewhat          leave the score alone
    c < 0.85   familiar          lower by one
    c >= 0.85  very familiar     collapse to Risk 1

`tests/unit/services/test_hazard_floor.py` covers all four branches as pure functions.
This file asks a different question: which of them a login can actually reach.

**The answer is two of the four, and the reason is a measurement, not an opinion.**
Device credibility never rises above its 0.2 prior. Measured on a user whose four
history rows carry exactly the device hash of the login being scored, the engine logs
`Evaluating device credibility. Number of successes 0 | failures 0 | history 0` while
the network half of the same login logs `successes 4 | failures 0 | history 4`. The
cause is visible in the hashes: a single login computes two different device hashes for
one context, stores one of them, and looks up credibility with the other, so nothing
ever matches. The network hash has no such problem and matches exactly.

Because device credibility is pinned at 0.2 and carries the larger weight, c can only
be 0.55*0.2 + 0.45*network. With network credibility at either its own 0.2 prior or
1.0, that is **0.20 or 0.56** and nothing else. The first raises; the second is the
no-change band. Both lowering bands sit above the highest reachable value, so in
practice the familiarity adjustment can only ever *raise* risk, never lower it.

That also explains something the matrix could not: the hazard floor, which exists to
stop familiarity from undoing a hazard escalation, guards a branch that no login
reaches. It is real code, correct, and currently unreachable.
"""

import re

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# The boundaries in `_adjust_for_credibility`, named so a failure message can say which
# band it expected rather than quoting a number.
UNFAMILIAR_BELOW = 0.30
NO_CHANGE_BELOW = 0.60
LOWERS_BY_ONE_BELOW = 0.85

FAMILIARITY = re.compile(r"familiarity ([0-9.]+)")

# Highest value reachable while device credibility is stuck at its prior.
MAX_REACHABLE = 0.55 * 0.2 + 0.45 * 1.0


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
    """K01. The `c < 0.3` branch, which is the one that does the work today.

    A login from an address the user has never used drops network credibility to its
    prior, and with the device half already at its prior the combined value is 0.20.
    """
    result = run_in(realm, "K01", {"xff": "62.2.0.1"})

    familiarity = reported_familiarity(result["why"])
    assert familiarity is not None, (
        f"no familiarity value was reported, so the adjustment did not run.\n"
        f"  why: {result['why']}"
    )
    assert familiarity < UNFAMILIAR_BELOW, (
        f"a login from an unused address reported familiarity {familiarity}, which is "
        f"not in the unfamiliar band.\n  why: {result['why']}"
    )
    assert "raising" in result["why"], (
        f"familiarity {familiarity} is below {UNFAMILIAR_BELOW} but the level was not "
        f"raised.\n  why: {result['why']}"
    )
    assert result["risk"] == 3, (
        f"the unfamiliar branch should force Risk 3, got {result['risk']}"
    )


def test_a_familiar_network_leaves_the_score_alone(realm):
    """K02. The `0.3 <= c < 0.6` branch, and the other side of the K01 boundary.

    The same login from the user's usual address. This is the highest familiarity a
    login can currently reach, which is why it is also the evidence for the two tests
    below.
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


# --- K03, K04: the bands no login can reach -------------------------------


@pytest.mark.parametrize(
    "band_name,threshold",
    [
        pytest.param("lowers by one", LOWERS_BY_ONE_BELOW, id="the-0.6-band"),
        pytest.param("collapses to Risk 1", 1.01, id="the-0.85-band"),
    ],
)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Neither lowering band can be reached, because device credibility never rises "
        "above its 0.2 prior. Measured: on a user whose four history rows carry "
        "exactly the device hash of the login being scored, the engine logs "
        "'Evaluating device credibility. Number of successes 0 | failures 0 | history "
        "0', while the network half of the same login logs 'successes 4 | failures 0 | "
        "history 4'. The cause is in the hashes: one login computes two different "
        "device hashes for a single context, stores one and looks up credibility with "
        "the other, so no history row ever matches; the network hash matches exactly "
        "and its credibility works. Since c = 0.55*device + 0.45*network and device is "
        "pinned at 0.2, the highest reachable c is 0.56, below the 0.6 boundary. So the "
        "familiarity adjustment can only raise risk, never lower it, and a returning "
        "user on a known device gets no benefit from being recognised. It also means "
        "the hazard floor guards a branch nothing reaches. Fixing it is a decision "
        "about which hash is canonical, so it is flagged rather than changed."
    ),
)
def test_a_familiar_device_can_lower_the_level(realm, band_name, threshold):
    """K03, K04. The half of the mechanism that never runs.

    Driven with the friendliest login available: nothing changed at all, the user's
    own device and their usual address. If any login can reach a lowering band, this
    one can.
    """
    result = run_in(realm, "K03", {}, prior_decision=3)

    familiarity = result["familiarity"]
    assert familiarity is not None, "the engine logged no credibility for this login"
    assert familiarity >= NO_CHANGE_BELOW, (
        f"the most familiar login available computed familiarity {familiarity:.2f} "
        f"(device {result['device_credibility']}, network "
        f"{result['network_credibility']}), below the {NO_CHANGE_BELOW} needed to "
        f"reach the '{band_name}' band. The reachable maximum is {MAX_REACHABLE:.2f}."
    )


def test_device_credibility_never_leaves_its_prior(realm):
    """K07. The measurement the two xfails rest on, pinned so it cannot drift quietly.

    A login whose four history rows carry exactly its own device hash should have a
    device credibility computed from four successes. It has none: the lookup finds no
    matching row and returns the 0.2 prior, while the network half of the same login
    finds all four and computes 1.0.

    Companion to the xfail above. That one says the lowering bands should be
    reachable; this records precisely how far from reachable they are and why. If
    device credibility is fixed, both fail together and are updated together, which is
    the point: a partial fix must not move the ceiling silently.
    """
    result = run_in(realm, "K07", {})

    device = result["device_credibility"]
    network = result["network_credibility"]
    assert device is not None, "the engine logged no credibility for this login"

    assert device == pytest.approx(0.2, abs=0.001), (
        f"device credibility is now {device}, where this test recorded the 0.2 prior. "
        f"If the hash mismatch was fixed, update this test and "
        f"test_a_familiar_device_can_lower_the_level together."
    )
    assert network > device, (
        f"the network half computed {network} from the same history rows that left "
        f"the device half at {device}, which is the asymmetry this test exists to "
        f"record. If both are now at the prior, something else broke."
    )

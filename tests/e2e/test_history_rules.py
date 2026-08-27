"""Rules that depend on a user's history rather than on this login's context.

The N, Q and X families of tests/e2e/coverage-plan.md.

The matrix seeds one shape of history and varies the login. These vary the *history*
and hold the login still, which is the only way to reach three things it never touches:

- **N, the drop-down decay.** A clean login relaxes one level below the last decision,
  or two if the account has been quiet longer than `DROP_DOWN_DECAY_DAYS`. Entirely
  uncovered before this, in a mechanism that only ever lowers risk.
- **Q, the history gate boundary.** The matrix has untrained users and fully trained
  ones. Neither says what happens at exactly `MIN_AUTH_EVENTS`.
- **X, signals the matrix only trips by accident.** `impossible_travel` and
  `time_interval` fire in `C01` as side effects of its setup, so nothing would notice
  if they stopped. `client` fires nowhere at all.

**Why some of these need their own realm.** The decay only runs when *nothing* changed,
and a long quiet period is itself a change: a 36-day gap moves `time_interval`, which
puts the login on the scoring path instead. Switching that one signal off is what makes
the decay observable, and is stated in each fixture rather than hidden.
"""

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# The clone lays its rows out one per day, oldest at `days_ago_of_oldest`, so with four
# training logins the newest lands four days later. These name the *gap since the last
# login*, which is what the decay measures, rather than the raw argument.
TRAINING_ROWS = 4


def days_ago_for_gap(gap_days: int) -> int:
    """`days_ago_of_oldest` that leaves the most recent login `gap_days` ago."""
    return gap_days + TRAINING_ROWS


def run_in(realm_run, row_id: str, delta: dict, **kwargs) -> dict:
    original = lib.REALM
    lib.REALM = realm_run["run"].realm
    try:
        result = lib.run_row(
            realm_run["token"], realm_run["golden_id"], row_id, delta, **kwargs
        )
        realm_run["run"].track(result["user_id"])
        return result
    finally:
        lib.REALM = original


def trained_realm(overrides: dict | None = None, target: int | None = None):
    with env.MatrixRun(overrides=overrides) as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)
            needed = target or int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
            lib.train(lib.BASELINE_CONTEXT, username, golden_id, target=needed)
            if lib.completed_logins(golden_id) < needed:
                pytest.fail("could not train the golden profile past the history gate")
            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original


@pytest.fixture(scope="module")
def quiet_realm():
    """A realm where a long absence is not itself a changed signal.

    `time_interval` compares this login's gap against the user's usual rhythm, so a
    36-day silence trips it, and a login with a changed signal never reaches the decay
    at all. Disabling that one parameter is the difference between observing the decay
    and observing why it did not run. `inactive_account` stays enabled, because its
    threshold is 40 days and the longest gap here is under that.
    """
    yield from trained_realm({"disabled": {"time_interval"}})


@pytest.fixture(scope="module")
def standard_realm():
    yield from trained_realm()


# --- N: the drop-down decay ------------------------------------------------


def test_a_clean_login_relaxes_one_level_below_the_last_decision(quiet_realm):
    """N02. The ordinary case: a quiet return, recently.

    Also the control for N01. Without it, "decayed by two" cannot be told apart from
    "decayed by however much it always decays".
    """
    result = run_in(
        quiet_realm, "N02", {}, prior_decision=3, days_ago_of_oldest=days_ago_for_gap(4)
    )

    assert result["risk"] == 2, (
        f"a clean login after history recorded at Risk 3 gave Risk {result['risk']}, "
        f"expected one step down to 2.\n  why: {result['why']}"
    )


def test_a_long_absence_relaxes_by_the_configured_number_of_steps(quiet_realm):
    """N01, N04. A stale escalation is forgiven faster.

    `DROP_DOWN_DECAY_DAYS` is 30 and `DROP_DOWN_DECAY_STEPS` is 2, so history recorded
    at Risk 3 and untouched for over a month should come back at Risk 1 rather than
    Risk 2. Read together with N02, which is the same setup inside the window.
    """
    result = run_in(
        quiet_realm, "N01", {}, prior_decision=3,
        days_ago_of_oldest=days_ago_for_gap(36),
    )

    assert result["risk"] == 1, (
        f"a clean login after 36 quiet days gave Risk {result['risk']}. The decay "
        f"should apply {env._engine_scoring_env()['DROP_DOWN_DECAY_STEPS']} steps "
        f"past {env._engine_scoring_env()['DROP_DOWN_DECAY_DAYS']} days, taking Risk "
        f"3 to Risk 1.\n  why: {result['why']}"
    )


def test_the_decay_never_takes_a_level_below_the_minimum(quiet_realm):
    """N03. The clamp, and the message that explains it.

    Two steps below Risk 2 is zero, which is not a risk level. Worth asserting because
    the arithmetic is a subtraction and the floor is a `max()` that could be dropped
    without any other test noticing.
    """
    result = run_in(
        quiet_realm, "N03", {}, prior_decision=2,
        days_ago_of_oldest=days_ago_for_gap(36),
    )

    assert result["risk"] == 1, (
        f"decaying two steps from Risk 2 gave Risk {result['risk']}, which is below "
        f"the minimum.\n  why: {result['why']}"
    )


def test_a_login_that_is_already_at_the_minimum_says_so(quiet_realm):
    """N03b. The explanation an operator reads when nothing moved.

    A user already at Risk 1 cannot decay further, and the engine says so explicitly
    rather than silently reporting the same level. That message is the only difference
    between "nothing to do" and "the decay did not run", which matters when reading a
    log to work out why a level is stuck.
    """
    result = run_in(quiet_realm, "N03b", {}, prior_decision=1)

    assert result["risk"] == 1
    assert "already at the minimum" in result["why"], (
        f"a clean login at Risk 1 did not explain why it stayed there.\n"
        f"  why: {result['why']}"
    )


# --- Q: the history gate boundary -----------------------------------------


def test_one_login_short_of_the_threshold_still_reads_the_gate(standard_realm):
    """Q01. The boundary from below.

    The matrix proves an untrained user is gated and a trained one is not. Neither
    shows where the line is, so an off-by-one in the comparison would pass both.
    """
    needed = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
    result = run_in(standard_realm, "Q01", {}, clone=True, rows_to_copy=needed - 1)

    assert "not enough history" in result["why"], (
        f"a user with {needed - 1} logins, one short of the {needed} required, was "
        f"scored rather than gated.\n  why: {result['why']}"
    )


def test_exactly_the_threshold_is_scored_rather_than_gated(standard_realm):
    """Q02. The boundary from above, one login later."""
    needed = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
    result = run_in(standard_realm, "Q02", {}, clone=True, rows_to_copy=needed)

    assert "not enough history" not in result["why"], (
        f"a user with exactly {needed} logins, the documented threshold, was still "
        f"gated. The comparison is off by one in the other direction.\n"
        f"  why: {result['why']}"
    )


# --- X: signals the matrix only trips by accident -------------------------


def test_signing_in_to_a_different_client_fires_the_client_signal(standard_realm):
    """X01. The one signal no matrix row touches.

    `client` is the application being signed in to, weight 1. Every matrix row uses
    the same client, so the signal has never fired anywhere in the suite and could
    have been broken since it was written.
    """
    token = standard_realm["token"]
    second = lib.create_public_client(token, "second-login")

    result = run_in(standard_realm, "X01", {"client": second})

    assert "the application being signed in to" in result["why"], (
        f"signing in to a different client did not report the client signal.\n"
        f"  why: {result['why']}"
    )


def test_impossible_travel_is_driven_deliberately(standard_realm):
    """X03. Today this only fires as a side effect of the concurrent-session row.

    Two logins minutes apart from cities far enough apart that no one could have
    travelled between them. Driven on purpose here so the signal has a test that
    fails when it breaks, rather than one that happens to notice.
    """
    def travel(token, username, user_id):
        outcome = lib.login({**lib.BASELINE_CONTEXT, "xff": "212.51.144.1"}, username)
        if not outcome.ok:
            raise AssertionError(
                f"could not establish the first location: {outcome.detail}"
            )
        return {"facts": {"first_login_from": "212.51.144.1 (CH)"}}

    result = run_in(standard_realm, "X03", {"xff": "8.8.8.8"}, before=travel)

    assert "impossible travel between logins" in result["why"], (
        f"a login from the US minutes after one from Switzerland did not report "
        f"impossible travel.\n  why: {result['why']}"
    )


def test_an_unusual_gap_between_logins_fires_the_time_interval_signal(standard_realm):
    """X04. Also only incidental to the concurrent-session row today.

    The seeded history is one login a day. Several logins moments apart are nothing
    like that rhythm, which is what the signal is for.

    Two prior logins, not one, and that is measured rather than chosen for symmetry
    with the concurrent-session row. The check calls the most recent interval
    FORBIDDEN when it falls below the *median* of all intervals, so a single extra
    login leaves the median dominated by the day-long gaps and the reading came back
    ACCEPTABLE. A second one moves the median far enough for the current gap to sit
    below it.

    The assertion is on the signal, not the level: `time_interval` carries weight 1,
    which is under the first band, so it fires without moving the level at all. A test
    written against the level would have looked like the signal was broken.
    """
    def immediately_before(token, username, user_id):
        for attempt in range(2):
            outcome = lib.login(lib.BASELINE_CONTEXT, username)
            if not outcome.ok:
                raise AssertionError(
                    f"could not place prior login {attempt + 1}: {outcome.detail}"
                )
        return {"facts": {"prior_logins": 2, "spacing": "seconds"}}

    result = run_in(standard_realm, "X04", {}, before=immediately_before)

    assert "time-between-logins pattern" in result["why"], (
        f"a login seconds after the previous one, against a history of one a day, "
        f"did not report an unusual interval.\n  why: {result['why']}"
    )


@pytest.mark.parametrize(
    "gap_days,should_be_dormant",
    [
        pytest.param(44, True, id="four-days-past-the-threshold"),
        pytest.param(36, False, id="four-days-inside-the-threshold"),
    ],
)
def test_dormancy_is_asserted_near_its_threshold(
    quiet_realm, gap_days, should_be_dormant
):
    """X06. The matrix uses 70 days against a 40-day threshold, which proves little.

    A threshold only means something when tested from both sides of it. Run in the
    quiet realm so the long gap does not also trip the interval signal and muddy the
    reading.
    """
    result = run_in(
        quiet_realm, f"X06-{gap_days}", {},
        days_ago_of_oldest=days_ago_for_gap(gap_days),
    )

    dormant = "long-dormant account" in result["why"]
    assert dormant is should_be_dormant, (
        f"history ending {gap_days} days ago was "
        f"{'not ' if should_be_dormant else ''}called dormant, against a 40-day "
        f"threshold.\n  why: {result['why']}"
    )

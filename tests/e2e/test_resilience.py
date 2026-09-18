"""What happens to a login when the engine does not answer.

The R family of tests/e2e/coverage-plan.md.

Every other functional test runs against a healthy engine, which means the code that
runs when the engine is *not* healthy has only ever run during incidents. That is the
worst time to discover it is wrong, and it is the code most likely to be wrong, because
nothing exercises it.

The property under test is simple to state: **a login must still complete, at the
realm's configured fallback level, when the engine cannot answer.** Not error, not hang,
not silently drop the step-up.

**How the failure is simulated.** The SPI reads the engine's address from the realm
attribute `adaptiveAuthEndpoint`, and `AdaptiveAuthUtils.getUserAdaptiveAuthDecision`
returns the fallback on any exception. So each test points a *throwaway realm* at an
address that fails in a particular way. The shared engine is never touched, nothing is
stopped or paused, and the tests are safe to run against a stack someone else is using.

**How the level is observed.** Not from a log. The realm asks for a different factor at
each level, so the step-up the browser is presented with *is* the level:

| Fallback level | What the login is asked for | Completes? |
| --- | --- | --- |
| 1 | nothing | yes |
| 2 | TOTP, which these users have not enrolled | no |
| 3 | an emailed code | yes |

That makes the assertion a statement about what a user experiences, rather than about
an internal value, and it proves the fallback was actually applied rather than merely
computed.
"""

import time

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# Addresses that fail in different ways, all resolved from inside the Keycloak
# container. The SPI appends "/decision" to whatever is configured.
BROKEN_ENDPOINTS = {
    # Discard port, closed: the connection is refused immediately.
    "refused": "http://127.0.0.1:9",
    # Keycloak itself, where /decision does not exist: a well-formed HTTP error.
    # SimpleHttp raises on any status >= 300, so this is the non-2xx path.
    "http_error": "https://keycloak:8443/realms/master",
    # TEST-NET-3, which is not routed: packets are dropped rather than refused, so
    # this is the connect-timeout path rather than the connection-error path.
    "blackhole": "http://203.0.113.253:8095",
}

# What the login should be asked for at each fallback level, and whether it can finish.
EXPECTED_BY_LEVEL = {
    1: {"step": None, "completes": True},
    2: {"step": "totp-required", "completes": False},
    3: {"step": "email-otp", "completes": True},
}


@pytest.fixture(scope="module")
def broken_realm():
    """One throwaway realm, repointed per test, deleted afterwards.

    Module scoped because realm creation and its parameter write are the slow part and
    nothing here depends on the realm's history. Each test sets the two attributes it
    needs, so tests do not inherit each other's configuration.
    """
    with env.MatrixRun() as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            yield run
        finally:
            lib.REALM = original


def configure(token: str, endpoint: str, fallback: str | None,
              failure_mode: str | None = None) -> None:
    """Point the realm at `endpoint` and set (or remove) its fallback level and
    failure mode.

    Read-modify-write, because the admin API *replaces* the realm attribute map rather
    than merging into it. A partial PUT here would drop the AMFA attributes and break
    every login in the realm, which is a mistake this suite has made before.
    """
    attributes = dict(lib.realm_attributes(token))
    attributes[env.ADAPTIVE_AUTH_ENDPOINT] = endpoint
    if fallback is None:
        attributes.pop(env.FALLBACK_RISK_ATTRIBUTE, None)
    else:
        attributes[env.FALLBACK_RISK_ATTRIBUTE] = fallback
    if failure_mode is None:
        attributes.pop(env.FAILURE_MODE_ATTRIBUTE, None)
    else:
        attributes[env.FAILURE_MODE_ATTRIBUTE] = failure_mode
    lib.set_realm_attributes(token, attributes)


def login_against_broken_engine(broken_realm, endpoint_key: str, fallback: str | None,
                                timeout: float = 20.0, failure_mode: str | None = None):
    """Configure the realm, run one login, and report what the user experienced."""
    token = lib.admin_token()
    configure(token, BROKEN_ENDPOINTS[endpoint_key], fallback, failure_mode)

    username, user_id = lib.create_user(token, f"r-{endpoint_key[:4]}")
    broken_realm.track(user_id)

    started = time.monotonic()
    outcome = lib.login(lib.BASELINE_CONTEXT, username, timeout=timeout)
    elapsed = time.monotonic() - started
    return outcome, elapsed


@pytest.mark.parametrize(
    "endpoint_key",
    [
        pytest.param("refused", id="connection-refused"),
        pytest.param("http_error", id="http-error-response"),
    ],
)
@pytest.mark.parametrize("level", [1, 2, 3], ids=lambda v: f"fallback-{v}")
def test_a_login_still_completes_at_the_configured_fallback_when_the_engine_fails(
    broken_realm, endpoint_key, level
):
    """R01, R02. The engine is unreachable or answers an error; the realm's level wins.

    Parametrized across both failure shapes and all three usable levels, because the
    interesting claim is not "it falls back" but "it falls back to the level the realm
    asked for". A fallback that ignored the attribute and always used one level would
    pass a single-level test.
    """
    expected = EXPECTED_BY_LEVEL[level]
    outcome, _ = login_against_broken_engine(broken_realm, endpoint_key, str(level))

    if expected["step"] is None:
        assert outcome.steps == ["screenRes", "password"], (
            f"with the engine {endpoint_key} and fallbackRisk {level}, the login was "
            f"asked for {outcome.steps}, but Risk 1 should ask for nothing beyond the "
            f"password. detail: {outcome.detail}"
        )
    else:
        assert expected["step"] in outcome.steps, (
            f"with the engine {endpoint_key} and fallbackRisk {level}, the login was "
            f"asked for {outcome.steps}, which does not include "
            f"{expected['step']!r}. The realm's fallback level was not applied. "
            f"detail: {outcome.detail}"
        )

    assert outcome.ok is expected["completes"], (
        f"with the engine {endpoint_key} and fallbackRisk {level}, login completion "
        f"was {outcome.ok}, expected {expected['completes']}. steps: {outcome.steps}, "
        f"detail: {outcome.detail}"
    )


def test_a_realm_with_no_fallback_attribute_still_lets_people_log_in(broken_realm):
    """R04. A missing attribute must not break every login in the realm.

    This is not hypothetical. The admin API replaces the realm attribute map, so a
    single PUT that omits the AMFA attributes removes them, and that has happened here
    before. The SPI's answer is to use its own HIGH_RISK_LEVEL, which is 3, so the
    login should be challenged rather than refused or waved through.
    """
    outcome, _ = login_against_broken_engine(broken_realm, "refused", None)

    assert "email-otp" in outcome.steps, (
        f"with no fallbackRisk attribute and an unreachable engine, the login was "
        f"asked for {outcome.steps}. The SPI documents Risk 3 for this case, which "
        f"asks for an emailed code. detail: {outcome.detail}"
    )
    assert outcome.ok, (
        f"a realm with no fallbackRisk attribute could not complete a login at all: "
        f"{outcome.detail}. Erring high must not mean locking everyone out."
    )


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param("0", id="below-the-range"),
        pytest.param("9", id="above-the-range"),
        pytest.param("banana", id="not-a-number"),
        pytest.param("", id="empty-string"),
    ],
)
def test_an_unusable_fallback_setting_falls_back_to_a_challenge(
    broken_realm, configured
):
    """R05. A misconfigured fallback level is treated as high risk, not as Risk 1.

    The direction matters more than the value. A typo in a realm attribute must not be
    the thing that silently removes the step-up for that realm, so the SPI's documented
    behaviour is to ignore anything outside 1-4 and use HIGH_RISK_LEVEL.
    """
    outcome, _ = login_against_broken_engine(broken_realm, "refused", configured)

    assert "email-otp" in outcome.steps, (
        f"fallbackRisk={configured!r} produced steps {outcome.steps}. An unusable "
        f"setting must be treated as high risk, not as no risk. detail: "
        f"{outcome.detail}"
    )


@pytest.mark.parametrize(
    "endpoint_key",
    [
        pytest.param("refused", id="connection-refused"),
        pytest.param("http_error", id="http-error-response"),
    ],
)
@pytest.mark.parametrize("level", [1, 2, 3], ids=lambda v: f"fallback-{v}")
def test_a_mandatory_realm_denies_the_login_regardless_of_the_fallback_level(
    broken_realm, endpoint_key, level
):
    """R06. Without adaptiveAuthFailureMode, there is no way to configure "deny
    the login if the engine can't be reached" at all -- the only lever is the
    numeric fallbackRisk value, and even setting it to 4 only denies if the
    admin also happens to leave that level unsatisfiable. adaptiveAuthFailureMode
    =mandatory makes the choice explicit: the login must be denied outright,
    regardless of what fallbackRisk is set to (unlike R01/R02, where fallbackRisk
    is the whole story).
    """
    outcome, _ = login_against_broken_engine(
        broken_realm, endpoint_key, str(level), failure_mode="mandatory"
    )

    assert outcome.ok is False, (
        f"adaptiveAuthFailureMode=mandatory with the engine {endpoint_key} and "
        f"fallbackRisk {level} still let the login complete (steps: {outcome.steps}, "
        f"detail: {outcome.detail}). A mandatory realm must never proceed on any "
        f"fallback level when the engine cannot be consulted."
    )


def test_a_mandatory_realm_with_no_fallback_attribute_still_denies(broken_realm):
    """R06b. Companion to R04: mandatory mode must override even the "no attribute"
    case, which R04 established still lets a login through in advisory mode."""
    outcome, _ = login_against_broken_engine(
        broken_realm, "refused", None, failure_mode="mandatory"
    )

    assert outcome.ok is False, (
        f"adaptiveAuthFailureMode=mandatory with no fallbackRisk attribute still let "
        f"the login complete: steps={outcome.steps}, detail={outcome.detail}"
    )


@pytest.mark.slow
def test_a_mandatory_realm_denies_the_login_when_the_engine_times_out(broken_realm):
    """R06d. Companion to R06: the finding names four unreachable-engine shapes
    (refused, HTTP error, timeout, TLS/certificate error) and R06 only covered the
    first two directly. The underlying code path (one catch (Exception e) around the
    same SimpleHttp call, for connect/read timeouts alike) is identical for all four,
    but this closes the gap explicitly rather than leaving the timeout shape
    unverified for mandatory mode specifically."""
    outcome, elapsed = login_against_broken_engine(
        broken_realm, "blackhole", "3", timeout=BLACKHOLE_CLIENT_TIMEOUT,
        failure_mode="mandatory",
    )

    assert outcome.ok is False, (
        f"adaptiveAuthFailureMode=mandatory with a blackholed (timed-out) engine "
        f"still let the login complete after {elapsed:.0f}s: steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )
    assert elapsed < ACCEPTABLE_HOLD_SECONDS, (
        f"a mandatory-mode denial took {elapsed:.0f}s waiting on a blackholed engine, "
        f"against a budget of {ACCEPTABLE_HOLD_SECONDS}s -- denying should not take "
        f"any longer than falling back does."
    )


def test_advisory_is_the_default_when_failure_mode_is_unset(broken_realm):
    """R06c. Backward compatibility: a realm that never heard of
    adaptiveAuthFailureMode must proceed at the configured fallback level, not
    deny -- an unset attribute must never be silently stricter than the realm
    intended by simply not opting in."""
    outcome, _ = login_against_broken_engine(
        broken_realm, "refused", "1", failure_mode=None
    )

    assert outcome.ok is True, (
        f"with adaptiveAuthFailureMode unset (implicit advisory) and fallbackRisk 1, "
        f"the login did not complete: steps={outcome.steps}, detail={outcome.detail}. "
        f"An unset failure mode must default to advisory, not mandatory."
    )


# How long a login may be held while the SPI waits on an engine that never answers.
# Not a tuned number: it is roughly the point past which a person, a load balancer or
# an impatient reverse proxy has already given up, so a hold longer than this is an
# outage whatever the eventual answer is.
# The SPI sets a 5s connect/read timeout on both engine calls. The auth-context call
# runs before the decision call and each can spend the full budget, so a blackholed
# engine costs up to ~10s plus the rest of the flow. 20 gives headroom without being so
# loose that a regression back to Keycloak's default timeouts would pass.
ACCEPTABLE_HOLD_SECONDS = 20

# The client must outlast Keycloak, or the test measures its own patience instead of
# the product's. Observed holds are 150s to 225s, so this leaves headroom above them.
# A first attempt used the default 20s and failed with a client-side ReadTimeout, which
# looks like a broken test rather than a slow product.
BLACKHOLE_CLIENT_TIMEOUT = 300


@pytest.fixture(scope="module")
def blackholed_login(broken_realm):
    """One login against an engine that never answers, measured once.

    A fixture rather than inline, because two separate things are worth asserting
    about the same event and it takes about two and a half minutes to produce. Running
    it twice to assert twice would be the slowest test in the repository for no gain.
    """
    return login_against_broken_engine(
        broken_realm, "blackhole", "3", timeout=BLACKHOLE_CLIENT_TIMEOUT
    )


@pytest.mark.slow
def test_a_login_survives_an_engine_that_never_answers(blackholed_login):
    """R03. A blackholed engine must still end in a challenge, not an error.

    Separate from the refused and error cases because this one depends on a timeout
    expiring rather than on an immediate failure. Packets are dropped rather than
    rejected, which is what a partitioned network or a hung process looks like, and is
    the failure the connection-refused case does not cover.
    """
    outcome, elapsed = blackholed_login

    assert outcome.ok, (
        f"a login against an engine that never answers did not complete after "
        f"{elapsed:.0f}s: {outcome.detail}. steps: {outcome.steps}"
    )
    assert "email-otp" in outcome.steps, (
        f"the login completed but was not challenged (steps: {outcome.steps}), so the "
        f"realm's fallback level was not applied once the wait ended"
    )
    print(f"\n  challenged correctly, after waiting {elapsed:.0f}s")


@pytest.mark.slow
def test_a_login_is_not_held_for_minutes_by_an_unresponsive_engine(blackholed_login):
    """R03b. Falling back correctly is not enough if it takes two minutes.

    Shares its measurement with the test above: that one asserts the outcome is right,
    this one asserts it arrives in time to matter.

    This was an xfail. With no timeout of its own the SPI inherited Keycloak's default
    HTTP client stack, and a blackholed engine held the login for 150s and 225s across
    two measured runs: the fallback was correct but arrived long after the user, and
    any load balancer in front, had given up. Both engine calls now set a 5s connect
    and read timeout.
    """
    _, elapsed = blackholed_login

    assert elapsed < ACCEPTABLE_HOLD_SECONDS, (
        f"the login was held for {elapsed:.0f}s waiting on an engine that never "
        f"answered, against a budget of {ACCEPTABLE_HOLD_SECONDS}s."
    )

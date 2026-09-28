"""What each risk level actually asks the user for.

The T family of tests/e2e/coverage-plan.md.

Every other test here is about reaching a level. This one is about what happens next,
which is the part a user experiences and the part the whole product exists to do. Before
this, only the email tier was ever completed: any row that reached Risk 2 stopped at
"TOTP requested" because no test user had ever enrolled an authenticator, so the TOTP
path had never run to completion anywhere in the suite.

**How a level is pinned.** Not by engineering a score. The realm's fallback level is
used instead, by pointing the realm at an engine address that cannot answer, exactly as
`test_resilience.py` does. That gives an exact, chosen level with no dependence on
scoring at all, which is what these tests want: the question is "what does Risk 2 ask
for", not "how does a login become Risk 2". It also means these tests keep working if
the scoring changes.
"""

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# A closed port inside the Keycloak container: the engine call fails at once and the
# realm's fallback level is used verbatim.
UNREACHABLE_ENGINE = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def realm():
    with env.MatrixRun() as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            attributes = dict(lib.realm_attributes(token))
            attributes[env.ADAPTIVE_AUTH_ENDPOINT] = UNREACHABLE_ENGINE
            lib.set_realm_attributes(token, attributes)
            yield {"run": run, "token": token}
        finally:
            lib.REALM = original


def pin_level(realm, level: int) -> None:
    attributes = dict(lib.realm_attributes(realm["token"]))
    attributes[env.FALLBACK_RISK_ATTRIBUTE] = str(level)
    lib.set_realm_attributes(realm["token"], attributes)


def user_at(realm, level: int, prefix: str):
    """A fresh user in a realm pinned to `level`."""
    pin_level(realm, level)
    username, user_id = lib.create_user(realm["token"], prefix)
    realm["run"].track(user_id)
    return username, user_id


# --- T01 and T03: the tiers that already worked ---------------------------


def test_the_lowest_level_asks_for_nothing_beyond_the_password(realm):
    """T01. The quiet path is genuinely quiet.

    Worth stating explicitly. Every other test asserts that a challenge appeared; if
    Risk 1 also challenged, none of them would notice, and the product would be a
    fixed second factor with extra steps.
    """
    username, _ = user_at(realm, 1, "t01")

    outcome = lib.login(lib.BASELINE_CONTEXT, username)

    assert outcome.ok, f"a Risk 1 login did not complete: {outcome.detail}"
    assert outcome.steps == ["screenRes", "password"], (
        f"Risk 1 asked for {outcome.steps}, which is more than a password"
    )


def test_the_email_tier_completes_with_a_mailed_code(realm):
    """T03. Implicit in most rows; asserted directly once, here."""
    username, _ = user_at(realm, 3, "t03")

    outcome = lib.login(lib.BASELINE_CONTEXT, username)

    assert "email-otp" in outcome.steps, (
        f"Risk 3 asked for {outcome.steps}, not an emailed code"
    )
    assert outcome.ok, f"the emailed code did not complete the login: {outcome.detail}"


# --- T02: the tier nothing could complete ---------------------------------


def test_the_totp_tier_completes_with_an_enrolled_authenticator(realm):
    """T02. The factor no test had ever answered.

    Until the harness could enrol, every Risk 2 row stopped at "TOTP requested" and
    the tier had never run to completion anywhere.
    """
    username, user_id = user_at(realm, 2, "t02")

    pin_level(realm, 1)
    secret = lib.enrol_totp(realm["token"], username, user_id)

    # A code is single use. Enrolment has just spent the current window's code, and
    # answering the challenge seconds later with the same one is rejected: the form is
    # simply re-served, which reads as a broken authenticator rather than as replay
    # protection working. Waiting for the next window is the difference.
    lib.wait_for_next_totp_window()

    pin_level(realm, 2)
    outcome = lib.login(lib.BASELINE_CONTEXT, username, totp_secret=secret)

    assert "totp" in outcome.steps, (
        f"an enrolled user was not challenged for a code at Risk 2: "
        f"steps={outcome.steps}"
    )
    assert outcome.ok, (
        f"an enrolled authenticator did not complete a Risk 2 login: "
        f"steps={outcome.steps}, detail={outcome.detail}"
    )


def test_a_user_without_an_authenticator_is_asked_to_enrol_and_may_proceed(realm):
    """T02b. What Risk 2 actually does to a user who has no second factor.

    Measured, and not what the rest of the suite assumed. The matrix records these
    logins as not completing, but that was the harness being unable to answer the
    form: the realm's Risk 2 branch offers *enrolment* to a user with no
    authenticator, and enrolling satisfies the step-up in the same session.

    Worth knowing rather than merely recording. It is the standard Keycloak
    conditional-factor pattern, and it means the second factor adds nothing against
    someone who already has the password and reaches an unenrolled account first: they
    can enrol their own authenticator and continue. Whether that is acceptable depends
    on how accounts are provisioned, which is a deployment decision rather than a bug,
    so this states the behaviour instead of asserting against it.
    """
    username, _ = user_at(realm, 2, "t02b")

    declined = lib.login(lib.BASELINE_CONTEXT, username)
    assert not declined.ok and "totp-required" in declined.steps, (
        f"a user who does not answer the enrolment form still completed the login: "
        f"steps={declined.steps}"
    )

    accepted = lib.login(lib.BASELINE_CONTEXT, username, allow_totp_enrolment=True)
    assert accepted.ok and "totp-enrol" in accepted.steps, (
        f"enrolling in response to the Risk 2 challenge did not complete the login: "
        f"steps={accepted.steps}, detail={accepted.detail}"
    )


# --- T05, T06: the negative paths of the emailed code ---------------------


def test_a_wrong_emailed_code_does_not_complete_the_login(realm):
    """T05. The step-up has to be a real gate, not a formality.

    Trivial to state and easy to get wrong: a challenge that accepts anything looks
    identical to a working one in every test that only checks completion.
    """
    username, _ = user_at(realm, 3, "t05")

    outcome = lib.login(lib.BASELINE_CONTEXT, username, bad_code=True)

    assert not outcome.ok, (
        f"a login completed after submitting a deliberately wrong code: "
        f"steps={outcome.steps}"
    )
    assert "email-otp-wrong" in outcome.steps


def test_an_emailed_code_cannot_be_used_for_a_second_login(realm):
    """T06. A code is single use.

    A replayable code weakens the factor to whoever has seen one message: an old
    email, a shared mailbox, a screenshot. Driven by completing one login normally,
    then starting another and answering it with the first code rather than the new one.
    """
    username, _ = user_at(realm, 3, "t06")

    lib.clear_mail()
    first = lib.login(lib.BASELINE_CONTEXT, username)
    assert first.ok, f"the first login did not complete: {first.detail}"

    used_code = lib.latest_code()
    assert used_code, "no code arrived for the first login"

    replayed = lib.login_with_fixed_code(lib.BASELINE_CONTEXT, username, used_code)

    assert not replayed.ok, (
        f"a code already spent on one login completed a second one. steps="
        f"{replayed.steps}"
    )


# --- T04: the level that is supposed to be a rejection --------------------


def test_the_rejection_level_does_not_let_the_login_through(realm):
    """T04. The top level stops the login rather than challenging it.

    This was an xfail. The realm's flow had only two risk conditions, risk-2-EQUAL and
    risk-3-GREATER_OR_EQUAL, so Risk 4 fell into the `>= 3` branch and was offered the
    same emailed code as Risk 3, which completed. The level the deny list forces was
    therefore indistinguishable from an ordinary step-up.

    The flow now has an `AMFA Deny` subflow, conditional on risk 4 or above, holding
    Keycloak's deny-access authenticator. It sits at priority 24, ahead of the two
    step-up branches, and that ordering is the whole mechanism: the High Risk branch
    matches `>= 3`, so placed after it a Risk 4 login would be handed a code and
    finish before the deny was ever reached.
    """
    username, _ = user_at(realm, 4, "t04")

    outcome = lib.login(lib.BASELINE_CONTEXT, username)

    assert not outcome.ok, (
        f"a Risk 4 login completed via {outcome.steps}. That is the level reserved "
        f"for a denylist match, so completing it means the deny list only asks for a "
        f"code."
    )
    assert "email-otp" not in outcome.steps, (
        f"a Risk 4 login was offered an emailed code before being refused: "
        f"{outcome.steps}. The deny branch must run before the step-up branches."
    )

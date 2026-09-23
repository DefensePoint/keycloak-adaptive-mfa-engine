"""Signing in the way a person does, in a real browser.

The B family of [browser-plan.md](browser-plan.md). Step 1: the fixture and the first
journey.

Opt-in. Marked `browser`, skipped with a clear reason when Playwright is not installed,
and slower than everything else here by an order of magnitude. It is not a second signal
matrix and should never become one: the HTTP driver has been shown to reach the same
decisions, so these journeys exist for what only a browser does. Running the page.

Run them:

    pip install playwright && playwright install chromium
    PYTHONPATH=. python3 -m pytest tests/e2e/test_browser_journeys.py

    # watch it happen
    PYTHONPATH=. python3 -m pytest tests/e2e/test_browser_journeys.py --headed
"""

import contextlib

import pytest

from tests.e2e import browser_lib as web
from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib
from tests.e2e.matrix_rows import signals_from_why

pytestmark = pytest.mark.browser


@contextlib.contextmanager
def in_realm(name: str):
    """Point the shared helpers at one realm for the duration of a call.

    `matrix_lib` keeps the realm in a module-level global, which is fine for a file
    holding one realm and quietly wrong for this one, which holds two. Setting it in a
    fixture that stays open leaves it pointing at whichever realm was created last, so
    a later test creates its user in one realm and signs in against the other: the
    password is rejected, the form comes back, and it reads as a broken login rather
    than a misdirected one. Scoping it to the call removes the ambiguity.
    """
    original = lib.REALM
    lib.REALM = name
    try:
        yield
    finally:
        lib.REALM = original


@pytest.fixture(scope="module")
def playwright():
    """One Playwright instance for the module, shared by every engine.

    One, not one per browser: the synchronous API refuses to start twice in a thread,
    so a second `sync_playwright()` for Firefox fails with "Please use the Async API
    instead", which is a confusing way to be told the instance should be shared.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="module")
def browser(playwright, request):
    """Chromium, headless unless --headed is passed.

    Module scoped because launching a browser costs about a second and nothing about a
    journey depends on a fresh *browser*; what has to be fresh is the context, and each
    login gets its own. Pinned by Playwright to a known build, which matters more here
    than in most suites: the browser's fingerprint is an input to the thing under test,
    so an unpinned upgrade would move the device signal and read as a product change.
    """
    headed = request.config.getoption("--headed", default=False)
    instance = playwright.chromium.launch(headless=not headed)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture(scope="module")
def realm():
    """A throwaway realm, exactly as the HTTP suites build one.

    The whole point of the driver returning a `LoginResult` is that everything else is
    reused rather than reimplemented: same realm creation, same parameters, same pinned
    scoring mode, same teardown.
    """
    with env.MatrixRun() as run:
        yield {"run": run, "token": lib.admin_token(), "realm": run.realm}


def test_a_new_user_signs_in_for_the_first_time(browser, realm):
    """B01. The whole flow, rendered, and completable by a person.

    A user who has never signed in has no history, so the engine gates them at a
    cautious level and the realm asks for an emailed code. That is the first experience
    every real user has, and until now no test had ever seen it in a browser.

    Four things are asserted, and each one fails differently. The screen-resolution step
    ran, which means the client-side JavaScript executed: nothing else in the suite
    proves that. The password form was rendered and accepted. The emailed code was
    asked for and accepted. And the flow ended with an authorization code, which is the
    only evidence that a person could actually get in.
    """
    username, user_id = new_user(realm, "b01")

    outcome = web.login(
        browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"]
    )

    assert "screenRes" in outcome.steps, (
        f"the screen-resolution step never ran, so the page's JavaScript did not "
        f"submit it. steps={outcome.steps}, ended at {outcome.final_url}"
    )
    assert "password" in outcome.steps, f"no password form was rendered: {outcome.steps}"
    assert "email-otp" in outcome.steps, (
        f"a first-time user was not asked for an emailed code. steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )
    assert outcome.ok, (
        f"the login did not complete in a browser: steps={outcome.steps}, "
        f"detail={outcome.detail}, url={outcome.final_url}"
    )


# --- a profile trained through the browser --------------------------------


@pytest.fixture(scope="module")
def browser_trained(browser, realm):
    """A golden profile whose history was produced by this browser.

    Trained through the browser rather than over HTTP on purpose. The device hash is
    computed from the user agent, screen resolution and language, and a browser
    presents those slightly differently from a hand-built request; a profile seeded by
    the HTTP driver would therefore look like a *different device* to a browser login,
    and the returning-user journey would be testing that mismatch rather than the
    quiet path.

    Training stops at the history gate, and the clones supply the low-risk history, for
    the reason documented in `clone_profile`: a clean login relaxes one level below the
    last decision, so history recorded at Risk 3 produces a Risk 2 login, which demands
    TOTP that these users cannot answer.
    """
    target = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
    username, golden_id = new_user(realm, "golden")

    for attempt in range(target):
        outcome = web.login(
            browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"]
        )
        assert outcome.ok, (
            f"training login {attempt + 1} of {target} did not complete: "
            f"steps={outcome.steps}, detail={outcome.detail}"
        )

    completed = lib.completed_logins(golden_id)
    assert completed >= target, (
        f"the browser-trained profile reached only {completed} of the {target} logins "
        f"the history gate needs, so the journeys below would read the gate"
    )
    return golden_id


def new_user(realm, prefix: str):
    """A tracked user in the given realm, whichever realm the globals point at."""
    with in_realm(realm["realm"]):
        username, user_id = lib.create_user(realm["token"], prefix)
    realm["run"].track(user_id)
    return username, user_id


def cloned_user(realm, golden_id: str, prefix: str) -> str:
    """A fresh user carrying a copy of the golden profile's history."""
    username, user_id = new_user(realm, prefix)
    lib.clone_profile(golden_id, user_id, prior_decision=1)
    return username


# --- B02, B03, B04 ---------------------------------------------------------


def test_the_resolution_the_browser_reports_is_the_one_the_engine_scores(
    browser, realm, browser_trained
):
    """B02. The client-side JavaScript is wired to the decision, end to end.

    Nothing else in the suite can show this. The HTTP driver posts a screen resolution
    it invented, so it proves the *field* is scored but says nothing about where the
    value comes from. Here the browser is given a screen the profile has never seen,
    its JavaScript reads `window.screen`, and the engine names the screen size among
    the signals that changed.

    Two assertions, because either half can break alone: the browser reported what it
    was configured with, and that value reached scoring.
    """
    username = cloned_user(realm, browser_trained, "b02")
    unusual = {**lib.BASELINE_CONTEXT, "screen_res": "1024x768"}

    since = lib.log_mark()
    outcome = web.login(browser, unusual, username, realm=realm["realm"])
    with in_realm(realm["realm"]):
        user_id = lib.user_id_of(realm["token"], username)
    verdict = lib.last_verdict(user_id, since) or {}

    assert outcome.reported_screen == "1024x768", (
        f"the page's JavaScript reported {outcome.reported_screen!r}, not the screen "
        f"the browser was given. steps={outcome.steps}"
    )
    assert "screen size" in verdict.get("why", ""), (
        f"the resolution the browser reported did not reach the decision.\n"
        f"  why: {verdict.get('why')}"
    )


def test_a_returning_user_on_the_same_browser_is_not_challenged(
    browser, realm, browser_trained
):
    """B03. The quiet path, which is what almost every real login is.

    Worth a browser journey of its own because it is the one outcome a user notices by
    its absence. If adaptive MFA challenges a known user on a known device, it is not
    adaptive, and no assertion elsewhere would catch that: every other test asserts a
    challenge *appeared*.
    """
    username = cloned_user(realm, browser_trained, "b03")

    outcome = web.login(browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"])

    assert outcome.ok, (
        f"a returning user could not sign in: steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )
    assert outcome.steps == ["screenRes", "password"], (
        f"a returning user on the same browser was asked for {outcome.steps}, which "
        f"is more than a password"
    )


def test_a_wrong_emailed_code_tells_the_user_it_was_wrong(browser, realm):
    """B04. The failure has to be visible, not merely correct.

    The HTTP test already proves a wrong code does not sign anyone in. What it cannot
    show is whether the person is *told*: a page that silently re-renders looks
    identical over HTTP and is unusable in practice.
    """
    username, user_id = new_user(realm, "b04")

    outcome = web.login(
        browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"], bad_code=True
    )

    assert not outcome.ok, f"a wrong code signed the user in: steps={outcome.steps}"
    assert outcome.page_text, "no page content was captured after the wrong code"
    assert "invalid" in outcome.page_text.lower(), (
        f"the page did not tell the user the code was wrong. Rendered text was:\n"
        f"  {outcome.page_text[:300]!r}"
    )


# --- B05, B06, B07: every factor, rendered ---------------------------------


@pytest.fixture(scope="module")
def pinned():
    """A realm whose risk level is chosen rather than earned.

    Same device as `test_step_up_factors.py`: point the realm at an engine address that
    cannot answer, and its fallback level becomes the level of every login. These three
    journeys are about what a level *renders*, not about how a login reaches one, so
    scoring is taken out of the picture entirely.
    """
    with env.MatrixRun() as run:
        token = lib.admin_token()
        with in_realm(run.realm):
            attributes = dict(lib.realm_attributes(token))
            attributes[env.ADAPTIVE_AUTH_ENDPOINT] = "http://127.0.0.1:9"
            lib.set_realm_attributes(token, attributes)
        yield {"run": run, "token": token, "realm": run.realm}


def at_level(pinned, level: int, prefix: str) -> str:
    with in_realm(pinned["realm"]):
        attributes = dict(lib.realm_attributes(pinned["token"]))
        attributes[env.FALLBACK_RISK_ATTRIBUTE] = str(level)
        lib.set_realm_attributes(pinned["token"], attributes)
    return new_user(pinned, prefix)[0]


def test_a_user_with_no_authenticator_can_set_one_up_and_continue(browser, pinned):
    """B05. The enrolment page, which no test had ever rendered.

    The HTTP suite established that Risk 2 offers enrolment and that enrolling
    satisfies the step-up. What it could not check is whether the page is usable: the
    QR code is an image, and an authenticator app is scanned, not parsed. A page that
    serves the secret in a hidden field but fails to render the QR passes every
    functional test and is useless to a person holding a phone.
    """
    username = at_level(pinned, 2, "b05")

    outcome = web.login(
        browser, lib.BASELINE_CONTEXT, username, realm=pinned["realm"],
        allow_totp_enrolment=True,
    )

    assert "totp-enrol" in outcome.steps, (
        f"Risk 2 did not offer enrolment: steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )
    assert outcome.qr_visible, (
        "the enrolment page did not render its QR code, so the secret could not be "
        "scanned. The manual key alone is not a usable setup flow."
    )
    assert "Mobile Authenticator Setup" in (outcome.page_text or ""), (
        f"the enrolment page did not render its heading. Text was:\n"
        f"  {(outcome.page_text or '')[:200]!r}"
    )
    assert outcome.ok, (
        f"enrolling did not complete the login: steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )


def test_a_user_with_an_authenticator_is_challenged_for_a_code(browser, pinned):
    """B06. The TOTP challenge form, also never rendered before this.

    Enrol first, then come back. The wait between them is not padding: a code is single
    use, so answering the challenge in the same 30 second window as the enrolment
    replays a spent code and the form is simply re-served, which reads as a broken
    authenticator rather than as replay protection working.
    """
    username = at_level(pinned, 2, "b06")

    enrolled = web.login(
        browser, lib.BASELINE_CONTEXT, username, realm=pinned["realm"],
        allow_totp_enrolment=True,
    )
    assert enrolled.totp_secret, f"enrolment produced no secret: {enrolled.steps}"

    lib.wait_for_next_totp_window()

    outcome = web.login(
        browser, lib.BASELINE_CONTEXT, username, realm=pinned["realm"],
        totp_secret=enrolled.totp_secret,
    )

    assert "totp" in outcome.steps, (
        f"an enrolled user was not challenged for a code: steps={outcome.steps}"
    )
    assert outcome.ok, (
        f"a valid code did not complete the login: steps={outcome.steps}, "
        f"detail={outcome.detail}"
    )


def test_a_denied_login_shows_an_error_page(browser, pinned):
    """B07. What a refusal looks like to the person refused.

    Risk 4 is the level the deny list forces, and until recently the flow had no branch
    that denied at all. Now that it does, the thing worth checking in a browser is not
    that the login fails, which the HTTP test covers, but that it fails *presentably*:
    an error page rather than a blank screen, a stack trace, or a redirect loop.
    """
    username = at_level(pinned, 4, "b07")

    outcome = web.login(browser, lib.BASELINE_CONTEXT, username, realm=pinned["realm"])

    assert not outcome.ok, f"a denied login completed: steps={outcome.steps}"

    text = (outcome.page_text or "").strip()
    assert text, "the denied login rendered a blank page"
    assert "denied" in text.lower(), (
        f"the page did not tell the user they were denied. Text was:\n  {text[:200]!r}"
    )
    for leak in ("Exception", "Traceback", "at org.keycloak", "java."):
        assert leak not in text, (
            f"the deny page leaked internals to the user ({leak!r}):\n  {text[:300]!r}"
        )


# --- B08, B09: sessions ----------------------------------------------------


def test_a_second_visit_in_the_same_session_skips_the_form(browser, realm):
    """B08. The SSO cookie, which no HTTP test exercises as a browser does.

    The value of this journey is that the *second* visit asks for nothing at all. A
    suite that only ever starts from a clean context would never notice if the cookie
    stopped working, and every user would silently be challenged on every visit.
    """
    username, user_id = new_user(realm, "b08")
    context = web.new_context(browser, lib.BASELINE_CONTEXT)

    try:
        first = web.login(
            browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"],
            browser_context=context,
        )
        assert first.ok, f"the first visit did not complete: {first.detail}"
        assert "password" in first.steps, f"unexpected first visit: {first.steps}"

        second = web.login(
            browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"],
            browser_context=context,
        )

        assert second.ok, f"the second visit did not complete: {second.detail}"
        assert second.steps == [], (
            f"a second visit in the same session was asked for {second.steps}; the "
            f"SSO cookie should have carried it straight through"
        )
    finally:
        context.close()


def test_signing_out_makes_the_next_visit_authenticate_again(browser, realm):
    """B09. That signing out actually ends the session.

    The counterpart to B08, and the one that matters for shared machines. Driven
    through the real confirmation page rather than by clearing cookies, because
    clearing cookies would prove the test can forget a session, not that Keycloak ends
    one.
    """
    username, user_id = new_user(realm, "b09")
    context = web.new_context(browser, lib.BASELINE_CONTEXT)

    try:
        first = web.login(
            browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"],
            browser_context=context,
        )
        assert first.ok, f"the first visit did not complete: {first.detail}"

        web.logout(context, realm["realm"])

        after = web.login(
            browser, lib.BASELINE_CONTEXT, username, realm=realm["realm"],
            browser_context=context,
        )

        assert "password" in after.steps, (
            f"after signing out, the next visit was let through on {after.steps}. "
            f"The session outlived the sign-out."
        )
    finally:
        context.close()


# --- B10: a login from somewhere else --------------------------------------


def test_signing_in_from_another_country_is_challenged(
    browser, realm, browser_trained
):
    """B10. The recognisable adaptive-MFA story, in a browser.

    The address is injected, which a real browser cannot do; see the note in
    `browser_lib`. Everything else is genuine, and without the injection this journey
    could not exist at all, because six signals derive from the client address and a
    browser has no way to present one.
    """
    username = cloned_user(realm, browser_trained, "b10")
    abroad = {**lib.BASELINE_CONTEXT, "xff": "193.99.144.80"}

    since = lib.log_mark()
    outcome = web.login(browser, abroad, username, realm=realm["realm"])
    with in_realm(realm["realm"]):
        user_id = lib.user_id_of(realm["token"], username)
    verdict = lib.last_verdict(user_id, since) or {}

    assert "country name" in verdict.get("why", ""), (
        f"a login from Germany against a profile built in Switzerland did not report "
        f"a country change.\n  why: {verdict.get('why')}"
    )
    assert outcome.steps != ["screenRes", "password"], (
        f"a login from another country was not challenged at all: {outcome.steps}"
    )


# --- B11: the two drivers agree --------------------------------------------


def test_both_drivers_reach_the_same_decision(browser, realm, browser_trained):
    """B11. The claim the whole HTTP suite rests on, checked without a person.

    `chrome_spotcheck.py` established this once, by hand. Automating it matters because
    the claim is load-bearing: 115 tests use the HTTP driver, and they are only
    meaningful if it presents a login the way a browser does.

    The comparison feeds the HTTP driver *what the browser actually presented*, read
    back from the context the engine stored, rather than what the test asked for. Those
    are not the same thing, and the difference is the point: a browser derives its own
    Accept-Language and sends headers the driver does not. Comparing against the test's
    intent would hide exactly the divergence this is looking for.
    """
    via_browser = cloned_user(realm, browser_trained, "b11w")
    with in_realm(realm["realm"]):
        browser_id = lib.user_id_of(realm["token"], via_browser)

    since = lib.log_mark()
    web_outcome = web.login(
        browser, lib.BASELINE_CONTEXT, via_browser, realm=realm["realm"]
    )
    web_verdict = lib.last_verdict(browser_id, since) or {}
    assert web_verdict, f"the browser login produced no verdict: {web_outcome.detail}"

    presented = web_outcome.presented
    assert presented, "no request headers were captured from the browser login"

    via_http = cloned_user(realm, browser_trained, "b11h")
    with in_realm(realm["realm"]):
        http_id = lib.user_id_of(realm["token"], via_http)
    mirrored = {
        "client": lib.BASELINE_CONTEXT["client"],
        "user_agent": presented["user_agent"],
        "accept_language": presented["accept_language"],
        "screen_res": web_outcome.reported_screen,
        "xff": presented["xff"],
    }

    since = lib.log_mark()
    with in_realm(realm["realm"]):
        lib.login(mirrored, via_http)
    http_verdict = lib.last_verdict(http_id, since) or {}
    assert http_verdict, "the HTTP login produced no verdict"

    assert http_verdict["risk"] == web_verdict["risk"], (
        f"the two drivers disagreed given the same presented context: browser said "
        f"Risk {web_verdict['risk']}, HTTP said Risk {http_verdict['risk']}.\n"
        f"  browser: {web_verdict['why']}\n  http:    {http_verdict['why']}"
    )
    assert sorted(signals_from_why(http_verdict["why"])) == sorted(
        signals_from_why(web_verdict["why"])
    ), (
        f"the two drivers reached the same level by different signals.\n"
        f"  browser: {web_verdict['why']}\n  http:    {http_verdict['why']}"
    )


# --- B12: a second browser engine ------------------------------------------


@pytest.fixture(scope="module")
def firefox(playwright):
    """A second engine, so "different browser" can mean something real.

    Skipped rather than failed when the Firefox build is absent: Chromium alone is the
    cheaper install, and one missing engine should not stop the other eleven journeys.
    """
    from playwright.sync_api import Error as PlaywrightError

    try:
        instance = playwright.firefox.launch(headless=True)
    except PlaywrightError as failure:
        pytest.skip(f"firefox is not installed: {failure}")
    try:
        yield instance
    finally:
        instance.close()


def test_a_different_browser_engine_is_a_different_device(browser, firefox, realm):
    """B12. Two engines, two devices, with genuine fingerprints.

    Every other journey overrides the user agent, which makes the browser present
    whatever the test says and reduces the device signal to an echo of its own input.
    Here both engines send their own, so the comparison is between two real
    fingerprints rather than two strings the test chose.

    Asserted on the hashes the engine computed rather than on a risk level, because the
    level depends on the profile and the claim here is narrower and sharper: these look
    like different devices.
    """
    native = {**lib.BASELINE_CONTEXT, "user_agent": None}

    chrome_user, chrome_id = new_user(realm, "b12c")
    firefox_user, firefox_id = new_user(realm, "b12f")

    from_chromium = web.login(browser, native, chrome_user, realm=realm["realm"])
    from_firefox = web.login(firefox, native, firefox_user, realm=realm["realm"])

    assert from_chromium.ok, f"the chromium login failed: {from_chromium.detail}"
    assert from_firefox.ok, f"the firefox login failed: {from_firefox.detail}"

    chromium_agent = (from_chromium.presented or {}).get("user_agent", "")
    firefox_agent = (from_firefox.presented or {}).get("user_agent", "")
    assert "Firefox" in firefox_agent, (
        f"the firefox run did not present a Firefox user agent, so the engines were "
        f"not really distinguished: {firefox_agent!r}"
    )
    assert chromium_agent != firefox_agent

    chromium_hash = lib.stored_device_hash(chrome_id)
    firefox_hash = lib.stored_device_hash(firefox_id)
    assert chromium_hash and firefox_hash, "no device hash was recorded for a login"
    assert chromium_hash != firefox_hash, (
        f"Chromium and Firefox were hashed as the same device ({chromium_hash[:16]}), "
        f"so the device signal cannot tell two browsers apart"
    )

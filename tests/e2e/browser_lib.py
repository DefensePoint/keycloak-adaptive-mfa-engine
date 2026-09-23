"""Signing in through a real browser.

The browser half of [browser-plan.md](browser-plan.md). Everything else in the suite
drives HTTP directly, which is fast and has been shown to reach the same decisions as
Chrome. What it cannot do is run the page: the client-side JavaScript, the rendered
templates, the cookie handling, the fact that a person could actually complete the flow.

**The driver returns the same `LoginResult` as `matrix_lib.login`.** That is the design
decision the rest of this file exists to serve. It means a journey can be run through
either driver and the results compared field by field, that verdict harvesting and
profile cloning work unchanged, and that adding a browser did not fork the harness.

**The context is set on the browser, not sent as headers.** `viewport` and `screen` are
what the JavaScript reads, `locale` becomes `Accept-Language`, `user_agent` replaces the
real one. The point of a browser test is that these travel the way they do for a user,
so they are configured on the context and left alone.

**One exception, stated loudly:** `X-Forwarded-For`. A browser cannot send it, and six
signals derive from the client address, so the geo journeys would be untestable without
it. When a context asks for one it is injected through request interception, and at that
moment the login is a real browser with one header a real browser would never send.
Everything else about it stays genuine.

In practice every journey here sends one, because they share `BASELINE_CONTEXT` with the
rest of the suite and it names an address. That is a deliberate trade for consistency
with the HTTP baselines, and it means no journey in this file is a completely unmodified
browser. Said plainly so a green run is not read as more than it is.
"""

from __future__ import annotations

import re

from tests.e2e.matrix_lib import (
    KC_BASE,
    PASSWORD,
    REALM,
    LoginResult,
    clear_mail,
    latest_code,
    totp_now,
)

# How long to wait for any single element. Playwright polls until it appears rather than
# sleeping, so this is an upper bound for a broken page, not a delay every test pays.
STEP_TIMEOUT_MS = 15_000

# Every form this driver knows how to answer. Waited for as a group at the top of each
# turn so the driver never samples a page mid-navigation: the screen-resolution step
# submits itself from JavaScript, so a navigation is in flight at a moment no explicit
# wait covers. Chromium happened to win that race and Firefox did not, which surfaced
# as "no actionable form" on a page that was plainly the login form.
KNOWN_FORMS = ", ".join((
    "#screenResForm",
    "#kc-form-login",
    "#kc-email-code-login-form",
    "#kc-totp-settings-form",
    "#kc-otp-login-form",
))

# Shorter than the step timeout: pages with no form at all are legitimate, the deny
# page being the obvious one, so this is how long to insist before accepting that.
SETTLE_TIMEOUT_MS = 5_000

_RES = re.compile(r"^(\d+)x(\d+)$")


def screen_from(context: dict) -> dict:
    """The screen size the browser should report, parsed from a matrix context.

    The JavaScript reads `window.screen.width/height`, so this is what ends up in the
    `screen_resolution` signal and in the device hash. Setting `screen` and `viewport`
    to the same value keeps the two consistent, which is not true of every real machine
    but is the simplest thing that is not misleading.
    """
    found = _RES.match(context.get("screen_res", ""))
    if not found:
        raise ValueError(f"screen_res {context.get('screen_res')!r} is not WIDTHxHEIGHT")
    width, height = int(found.group(1)), int(found.group(2))
    return {"width": width, "height": height}


def new_context(browser, context: dict):
    """A fresh browser context presenting the given login context.

    One per journey, never shared. A Playwright context is a cookie jar, and sharing one
    would reintroduce exactly the cross-test coupling the throwaway realm removes; two
    of the planned journeys are specifically about cookies.
    """
    size = screen_from(context)
    kwargs = {
        "viewport": size,
        "screen": size,
        "locale": context["accept_language"].split(",")[0],
        "ignore_https_errors": True,
    }
    # A context may ask for the engine's own user agent by setting None, which is what
    # the second-engine journey needs: overriding it would make Firefox present itself
    # as Chrome and the device signal could not tell them apart.
    if context.get("user_agent"):
        kwargs["user_agent"] = context["user_agent"]
    browser_context = browser.new_context(**kwargs)
    browser_context.set_default_timeout(STEP_TIMEOUT_MS)

    forwarded = context.get("xff")
    if forwarded:
        # See the module docstring: a browser cannot do this, and without it no
        # address-derived signal can be driven from a browser at all.
        browser_context.set_extra_http_headers({"X-Forwarded-For": forwarded})
    return browser_context


# Secondary actions that also submit their form. Clicking one instead of the primary
# control looks like a hang: "Resend code" re-issues the challenge and re-renders the
# same page, so the driver loops until its step budget runs out with no useful error.
SECONDARY_ACTIONS = ("resend", "cancel", "cancel-aia")


def submit(page, form_id: str) -> None:
    """Click the primary submit control inside one form.

    Scoped to the form and filtered by name rather than clicking a global `#kc-login`,
    because the ids are not consistent across this theme's pages: the login form has a
    submit with that id, the emailed-code form has two submit inputs with no id at all,
    and one of those is Resend.
    """
    exclusions = "".join(f":not([name='{name}'])" for name in SECONDARY_ACTIONS)
    control = page.locator(
        f"#{form_id} :is(input[type=submit], button[type=submit]){exclusions}"
    )
    # Wait for the navigation this click causes, not merely for a load state. Without
    # it the old DOM is still present when the caller looks again, the form it just
    # submitted is still attached, and the driver submits it a second time: the
    # symptom was a login that posted the password ten times and then gave up.
    with page.expect_navigation():
        control.first.click()


def authorize_url(realm: str, client: str) -> str:
    return (
        f"{KC_BASE}/realms/{realm}/protocol/openid-connect/auth"
        f"?client_id={client}&redirect_uri={KC_BASE}/e2e-callback"
        f"&response_type=code&scope=openid&state=b&nonce=b"
    )


def logout(browser_context, realm: str) -> None:
    """End the session the way a user does, through the confirmation page.

    Keycloak asks for confirmation when no id_token_hint is supplied, so clearing
    cookies from the test would not be the same act: it would prove the harness can
    forget a session, not that signing out ends one.
    """
    page = browser_context.new_page()
    try:
        page.goto(f"{KC_BASE}/realms/{realm}/protocol/openid-connect/logout")
        page.wait_for_load_state()
        confirm = page.locator("[name='confirmLogout']")
        if confirm.count():
            confirm.first.click()
            page.wait_for_load_state()
    finally:
        page.close()


def login(browser, context: dict, username: str, password: str = PASSWORD,
          realm: str | None = None, totp_secret: str | None = None,
          bad_code: bool = False, allow_totp_enrolment: bool = False,
          browser_context=None, on_page=None) -> LoginResult:
    """Drive one login to completion in a real browser.

    Mirrors `matrix_lib.login`: same steps vocabulary, same `LoginResult`, so a caller
    can swap drivers. Each branch waits for its form rather than assuming an order,
    because the flow the user gets depends on the risk level and that is the thing
    under test.

    `on_page` is called with the page after each step, for a journey that wants to
    assert something about what is rendered rather than only about the outcome.
    """
    result = LoginResult()
    realm = realm or REALM
    # A caller may pass a context to reuse, which is how the session journeys ask a
    # second question of the same browser. It owns the context and closes it; a context
    # created here is closed here.
    owned = browser_context is None
    browser_context = browser_context or new_context(browser, context)
    page = browser_context.new_page()

    # Watch the network rather than the DOM for the screen-resolution step. The page's
    # JavaScript submits that form as soon as the document is ready, which is usually
    # before the first poll, so checking for the form is a race the test loses on a
    # fast machine and wins on a slow one. The POST is unambiguous and cannot be
    # missed, and observing it is the only proof the JS ran at all.
    def note_request(request):
        body = request.post_data or ""
        if request.method == "POST" and "screenRes=" in body and (
            "screenRes" not in result.steps
        ):
            result.steps.append("screenRes")
            result.reported_screen = body.split("screenRes=", 1)[1].split("&")[0]

        # What the browser actually put on the wire, recorded once. The engine stores a
        # parsed form of the user agent rather than the string, so this is the only
        # place the presented headers can be recovered, and the parity journey needs
        # them: a browser derives its own Accept-Language and does not necessarily send
        # what the test asked for.
        if request.method == "POST" and result.presented is None:
            headers = request.headers
            result.presented = {
                "user_agent": headers.get("user-agent"),
                "accept_language": headers.get("accept-language"),
                "xff": headers.get("x-forwarded-for"),
            }

    page.on("request", note_request)

    try:
        clear_mail()
        page.goto(authorize_url(realm, context["client"]))

        for _ in range(10):
            page.wait_for_load_state()
            if "/e2e-callback" in page.url and "code=" in page.url:
                result.ok = True
                result.detail = "authorization code issued"
                return result

            # Let the page settle on something answerable. A timeout here is not a
            # failure: it means no known form appeared, which is what a denied login
            # looks like, and the branches below fall through to report the page.
            try:
                page.wait_for_selector(
                    KNOWN_FORMS, timeout=SETTLE_TIMEOUT_MS, state="attached"
                )
            except Exception:
                pass

            if on_page:
                on_page(page, result)

            # The step submits itself, so the driver only waits for it to go. If it is
            # still there after the timeout the JavaScript did not run, which is a real
            # failure worth naming rather than looping on: a user with JS disabled, or a
            # broken asset, would be stuck on exactly this page.
            if page.locator("#screenResForm").count():
                try:
                    page.wait_for_selector("#screenResForm", state="detached")
                except Exception:
                    result.steps.append("screenRes-not-submitted")
                    result.detail = (
                        "the screen-resolution form was still on the page after "
                        f"{STEP_TIMEOUT_MS}ms; its JavaScript did not submit it"
                    )
                    return result
                continue

            if page.locator("#kc-form-login").count():
                result.steps.append("password")
                page.fill("#username", username)
                page.fill("#password", password)
                submit(page, "kc-form-login")
                continue

            if page.locator("#kc-email-code-login-form").count():
                if bad_code:
                    result.steps.append("email-otp-wrong")
                    page.fill("#code", "000000")
                    submit(page, "kc-email-code-login-form")
                    # Captured after submitting, because the question is not only
                    # whether the code was rejected but whether the person is told.
                    result.page_text = page.inner_text("body")
                    result.detail = "submitted a deliberately wrong code"
                    return result
                code = latest_code()
                result.steps.append("email-otp" if code else "email-otp-missing")
                if not code:
                    result.detail = "no email code arrived"
                    return result
                page.fill("#code", code)
                submit(page, "kc-email-code-login-form")
                continue

            # Enrolment. Off by default for the same reason as the HTTP driver: it
            # changes the user's credentials, so a journey that did not ask for it
            # should see what a user without an authenticator sees.
            if page.locator("#kc-totp-settings-form").count():
                if not allow_totp_enrolment:
                    result.steps.append("totp-required")
                    result.detail = "TOTP enrolment offered; journey declined it"
                    result.page_text = page.inner_text("body")
                    return result
                secret = page.input_value("#totpSecret")
                result.totp_secret = secret
                result.steps.append("totp-enrol")
                result.page_text = page.inner_text("body")
                result.qr_visible = page.locator("#kc-totp-secret-qr-code").is_visible()
                page.fill("#totp", totp_now(secret))
                page.fill("#userLabel", "e2e-browser")
                submit(page, "kc-totp-settings-form")
                continue

            if page.locator("#kc-otp-login-form").count():
                if not totp_secret:
                    result.steps.append("totp-required")
                    result.detail = "TOTP requested; no authenticator enrolled"
                    return result
                result.steps.append("totp")
                page.fill("#otp", totp_now(totp_secret))
                submit(page, "kc-otp-login-form")
                continue

            # No form the driver recognises. That is not automatically a failure:
            # the deny branch ends here on purpose, with a rendered error page and
            # nothing to fill in. The page text is captured so the caller can tell an
            # intentional refusal from a blank page or a stack trace.
            result.detail = f"no actionable form at {page.url[:100]}"
            result.page_text = page.inner_text("body")
            return result

        result.detail = "flow did not settle within the step budget"
        return result
    finally:
        result.final_url = page.url
        if owned:
            browser_context.close()
        else:
            page.close()

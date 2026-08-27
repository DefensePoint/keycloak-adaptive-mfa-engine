# Browser end-to-end tests: signing in the way a person does

Third plan in this directory, after [signal-matrix-plan.md](signal-matrix-plan.md) (the
harness) and [coverage-plan.md](coverage-plan.md) (what is covered). This one is about
the one thing neither covers: a real browser, running the real page, doing what a user
does.

**Status:** complete. All twelve journeys pass, and the manual `chrome_spotcheck.py` has
been removed now that B11 checks driver parity automatically. What remains is B13, which
is a product question rather than test work.

---

## 1. What a browser adds, and what it does not

The existing suite drives HTTP directly. It uses the same form actions, cookies,
redirects, SPI and engine as a browser, and the parity journey has already shown that
given the same context it reaches the same decision, with the same signals and
byte-identical reasoning. So a browser suite is **not** going to find risk-scoring bugs.
Saying that plainly up front matters, because "we have browser tests" is easy to hear as
"the risk logic is now properly tested", and it would not be.

What only a browser exercises:

| | Why nothing else reaches it |
| --- | --- |
| **The client-side JavaScript** | `theme/keycloak-amfa/login/resources/js/index.js` reads `window.screen.width/height`, writes `#screenRes` and submits the form. No HTTP test runs it: the driver posts a value it made up. This is the *only* producer of a real screen resolution |
| **Real header fingerprints** | Chrome sends `sec-ch-ua`, `Sec-Fetch-*` and a full `Accept` set. The device and browser signals are derived from headers, so the driver's smaller set is a guess at what a user presents |
| **The custom templates** | `screen-resolution.ftl` and `login-mfa-email.ftl` are ours. A template that renders but is unusable, or an email whose code is unreadable, passes every test that only looks for a form id |
| **Cookies and sessions as a browser handles them** | The SSO cookie, sign-out, a second tab, the back button |
| **That the page works at all** | A CSP error, a broken asset or a JS exception fails no current test |

The JavaScript deserves particular attention. Its output feeds the `screen_resolution`
signal *and* the device hash, and the device hash is where the K03 bug lives. A browser
test is the only thing that would show what value a real screen actually produces.

---

## 2. What not to do

Do not re-run the signal matrix in a browser. Twenty-three rows at browser speed is
minutes instead of seconds, for decisions already proven identical. The browser suite
should be a **dozen journeys**, not a second matrix.

---

## 3. Tooling

**Playwright**, Python binding.

| | |
| --- | --- |
| Why not Selenium | Needs a matching driver binary, no auto-waiting, and the flakiness that follows |
| Why not the HTTP driver with more headers | It still cannot run the JavaScript, which is the main thing being bought |
| Cost | A dependency plus browser binaries, a few hundred MB, installed with `playwright install chromium` |
| Bonus | Request interception, which solves the address problem in section 5 |
| Bonus | Trace viewer: a failed run can be replayed frame by frame, which matters when a failure is "the form did not submit" |

Declared as an optional extra, not in the base requirements, so the existing suites keep
running on a machine with nothing but `requests`.

---

## 4. Architecture: swap the driver, keep the harness

Everything already built stays. `MatrixRun` still makes the throwaway realm, writes the
parameters and pins the scoring mode; `matrix_lib` still creates users, clones profiles
and reads verdicts from the engine log; Mailpit is still read over HTTP.

The only new piece is a login driver with the same shape as `lib.login`:

```
lib.login(context, username)            -> LoginResult    # HTTP, exists
browser.login(page, context, username)  -> LoginResult    # Playwright, new
```

Same `LoginResult`, so `run_row` and the verdict harvesting work unchanged, and a
journey can be run through either driver and compared. That is what makes the parity
test in B11 a two-line assertion rather than a second framework.

Chrome's context is set per test through Playwright's browser context rather than by
sending headers: `viewport` and `screen` for the resolution, `locale` for the language,
`userAgent` for the device. Those are what the JS and the header signals read.

---

## 5. The address problem, and its honest resolution

A browser cannot set `X-Forwarded-For`. Six of the nineteen signals are derived from the
client address, and every geo row in the matrix chooses one that way. Two options:

**Accept the limit.** The browser suite covers no geo signals and every journey runs from
the machine's own address. Simple and completely honest, but it rules out the
"signing in from a new country" journey, which is the most recognisable adaptive-MFA
story there is.

**Intercept the request.** Playwright can add a header to outgoing requests, so the
browser sends `X-Forwarded-For` even though a user's browser never would. This is
recommended, with the caveat written into the test: at that moment it is no longer
"exactly what a user does", it is a real browser with one injected header. Everything
else about it, the JS, the rendering, the cookies, remains genuine, and the alternative
is not testing the geo journeys at all.

Either way this is stated in the module docstring, so nobody reads a green browser suite
as proof that geolocation works for real users.

---

## 6. The journeys

Twelve, named the way the other plans name cases.

### First contact

| Id | Journey | What only the browser proves |
| --- | --- | --- |
| B01 | A new user signs in for the first time, is challenged, and gets in with the emailed code | **Done.** The whole flow renders and is completable by a person |
| B02 | The resolution the browser reports is the one the engine scores | **Done.** The JS runs, and its value reaches scoring |
| B03 | The same user signs in again from the same browser and is not challenged | **Done.** The quiet path, which is what most logins are |

### The factors

| Id | Journey | What only the browser proves |
| --- | --- | --- |
| B04 | A wrong emailed code shows an error on the page and does not sign the user in | **Done.** The failure is *visible*, not just rejected |
| B05 | A user with no authenticator is asked to enrol, scans the secret, and continues | **Done.** Asserts the QR actually renders |
| B06 | A returning user with an authenticator is challenged for a code and gets in | **Done.** The TOTP form, never rendered before |
| B07 | A denied login shows an error page, not a blank page or a stack trace | **Done.** Also asserts no internals leak |

### Sessions

| Id | Journey | What only the browser proves |
| --- | --- | --- |
| B08 | A second visit in the same session skips the form entirely | **Done.** The SSO cookie |
| B09 | After signing out, the factor is required again | **Done.** Driven through the real confirmation page |

### Context

| Id | Journey | What only the browser proves |
| --- | --- | --- |
| B10 | Signing in from another country is challenged | **Done.** Using the injected address |
| B11 | The same journey through both drivers reaches the same decision | **Done.** Replaces the manual `chrome_spotcheck.py`, now removed |
| B12 | The same journey in a second browser engine is scored as a different device | **Done.** Firefox against Chromium, both presenting their own user agent |

### One worth deciding on

`B13`, JavaScript disabled. The screen-resolution step depends on JS to submit itself, so
with JS off the login presumably cannot proceed at all. Whether that is acceptable is a
product question, and the test is only worth writing once it is answered. Raised here
because a browser suite is the only place the question can even be asked.

---

## 7. Determinism, browser edition

The existing guards still apply: throwaway realm, its own parameters, pinned scoring
mode, guarded bundled IP data. Browsers add their own.

**Never wait for a fixed time.** Playwright's auto-waiting on a selector is the whole
reason to prefer it. A `sleep` in a browser test is a flake with a delay fuse.

**One context per journey.** A Playwright browser context is a fresh cookie jar. Sharing
one across journeys reintroduces exactly the cross-test coupling the throwaway realm was
built to remove, and B08 and B09 are specifically *about* cookies.

**Headless by default, headed by flag.** Headless in CI; `--headed` when a person is
working out why something failed. Save a trace on failure.

**Pin the browser version.** Playwright pins browser builds to its own version, so the
device fingerprint is stable run to run. That matters here more than in most suites,
because the fingerprint *is* an input to the thing under test: an unpinned browser
upgrade would move the device signal and look like a product change.

**Keep the codes out of band.** Read the emailed code from Mailpit's API and compute TOTP
in Python, as now. Automating a mail client would be testing Mailpit.

---

## 8. Cost

| | |
| --- | --- |
| Per journey | about 2.5s, except B06 |
| B06 | 0 to 30s on top, waiting for a fresh TOTP window. A code is single use, so a challenge in the same window as the enrolment replays a spent one |
| Seven journeys, measured | 15s and 40s on two consecutive runs, the spread being B06's wait |
| Existing suites | unchanged; this is opt-in, marked, and deselected by default |
| CI | needs browser binaries in the image, `playwright install --with-deps chromium firefox` |
| Maintenance | the real cost. Browser tests rot faster than HTTP tests, and a suite nobody trusts gets skipped |

That last row is the argument for twelve journeys rather than forty. Every one should
earn its place by covering something no HTTP test can.

---

## 9. Sequencing

| Step | Work | Useful on its own? |
| --- | --- | --- |
| 1 | Playwright as an optional dependency, one browser fixture, B01 | Yes: proves the flow is completable by a browser, unattended |
| 2 | B02, B03, B04 | **Done** |
| 3 | B05, B06, B07 | **Done** |
| 4 | B08, B09 | **Done** |
| 5 | B10, B11, B12 | **Done** |
| 6 | Retire `chrome_spotcheck.py`, which B11 supersedes | **Done.** The suite has no manual step left |

Steps 1 to 3 are the useful unit. If it stops there, the result is still every factor
proven completable in a real browser, which is more than exists today.

---

## 10. Open questions

- **Where does this run?** The existing e2e suites need a live stack and are not in CI.
  A browser suite is a good forcing function for that, or it becomes another thing run
  by hand.
- **Which browsers?** Chromium alone is cheapest. Adding Firefox buys B12 and a genuinely
  different fingerprint. WebKit is likely not worth the third install.
- **B13**, whether a JS-less login should work at all.


---

## 11. What step 1 turned up

Three things the plan did not anticipate, all in the theme rather than the product, and
all of the kind only a browser finds.

**The submit controls are not consistent between pages.** The login form has a submit
with id `kc-login`; the emailed-code form has two submit inputs with *no id at all*, and
the second one is "Resend code". A driver that clicks a global `#kc-login` works on the
first page and hangs on the second, and clicking the wrong control there re-issues the
challenge and re-renders the same page, so the failure reads as a hang rather than a
mistake. `browser_lib.submit` therefore scopes to the form and excludes the known
secondary actions by name.

**The screen-resolution step cannot be observed by polling.** Its JavaScript submits as
soon as the document is ready, which is before the driver's first look on any reasonably
fast machine, so a DOM check is a race the test loses. It is watched on the network
instead: the POST carrying `screenRes=` is unambiguous, and catching it is the only
direct proof the JavaScript ran. The value it carried is recorded on the result, which
is what B02 will assert against.

**A page that never submits is a distinct failure.** If that form is still present after
the timeout, the driver now names it rather than looping to exhaustion: that is exactly
the state a user with JavaScript disabled would be in, which is the open question in
B13.


---

## 12. What steps 2 and 3 turned up

Nothing broken, which is itself worth recording: the enrolment page renders its QR, the
TOTP challenge works, and the deny branch added for T04 produces a proper Keycloak error
page reading "We are sorry... Access denied" with no internals leaked. Those three pages
had never been rendered by a test before.

Two things shaped how the journeys are written.

**The golden profile has to be trained through the browser.** The device hash is computed
from the user agent, screen resolution and language, and a browser presents those a little
differently from a hand-built request. A profile seeded over HTTP therefore looks like a
*different device* to a browser login, and B03 would have been measuring that mismatch
rather than the quiet path. Training costs four browser logins, which is the bulk of the
setup and buys a journey that means what it says.

**B06 cannot be hurried.** A TOTP code is single use, so the challenge has to fall in a
later window than the enrolment. That is 0 to 30 seconds of real waiting and there is no
way around it short of manipulating the clock, which would be testing the test.


---

## 13. What steps 4 to 6 turned up

Nothing wrong with the product. Sessions behave: the SSO cookie carries a second visit
through with no prompt at all, and signing out through the real confirmation page makes
the next visit authenticate again. Firefox and Chromium hash as different devices when
each presents its own user agent. The two drivers agree.

Three problems in the harness, all found by the browser and all worth recording because
each produced a symptom that pointed somewhere else.

**Two module-scoped fixtures both set `matrix_lib`'s realm global.** Once the second
realm existed, every later test created its user in one realm and signed in against the
other, so the password was rejected and the form came back. The symptom was a login
posting the password ten times and giving up, which reads as a broken login rather than
a misdirected one. The realm is now scoped to the call with `in_realm`, and the fixtures
do not touch the global. Worth knowing for anyone adding a file that holds more than one
realm.

**Waiting for a load state is not waiting for a navigation.** After submitting a form the
old DOM is briefly still there, so the driver saw the form it had just submitted and
submitted it again. `submit` now waits for the navigation its own click causes.

**Chromium and Firefox race differently.** The screen-resolution step submits itself from
JavaScript, so a navigation is in flight at a moment no explicit wait covers. Chromium
happened to win that race and Firefox did not, surfacing as "no actionable form" on a
page that was plainly the login form. The driver now waits for any form it knows how to
answer before deciding what it is looking at. A second engine earns its place partly by
finding this class of bug.

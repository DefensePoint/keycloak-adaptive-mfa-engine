# Risk-signal matrix: a replayable functional suite

**Status:** complete. All five steps are done. 23 rows run green against the live
stack with one strict xfail, a committed baseline catches a level moving on the rows
that cannot assert one directly, and the HTTP driver has been verified against a real
browser. Usage is documented in [README.md](README.md).

The goal is a table where each row is a login with a known context, and the last
columns are the risk level the engine chose and its own explanation of why. Run it
again next month and you should get the same table, or a diff that tells you exactly
what changed.

---

## 1. Why not every combination

The realm has 19 signals, 18 enabled. Treating each as binary is 2^18 = 262,144 rows,
which at roughly 4 seconds a login is about twelve days of continuous running, and
several signals have more than two states. A full cartesian product is not a test.

Instead the matrix is designed: every signal individually, every scoring rule at its
boundary, and the specific interactions that decide outcomes.

| Tier | Rows | Proves |
| --- | --- | --- |
| Baseline | 1 | trained user, nothing changed, Risk 1 |
| Single delta | 10 | each signal's contribution |
| Anonymiser | 2 | a real Tor exit, alone and combined with an unusual hour |
| Hard overrides | 3 | deny-list forces 4, allow-list caps at 2 |
| Hazard | 1 | many signals at once forces 3 |
| History gate | 3 | untrained user gates before any scoring |
| Sequence signals | 3 | concurrent sessions, a self-service password change, failed logins |

The weight-band tier was dropped as a separate group. Bands cannot be hit precisely
through the front door, because `event_cluster_label` at weight 3 fires on any context
change, so a chosen sum is not reachable. Instead **every** row asserts the arithmetic:
the weights of the signals the engine says changed must map to the band it says it
chose. That checks the scoring on all 19 rows rather than 8, and it uses the engine's
own list, so a signal firing unexpectedly is caught rather than assumed away.

---

## 2. What "replayable" means here

Three separate properties. A suite with only the third is noise.

| Property | Means | How |
| --- | --- | --- |
| Re-runnable | Twice in a row, same result, no manual cleanup | throwaway realm, unique users, row teardown |
| Reproducible | Same result at 03:00 or 17:00, on any machine | seed relative to now, neutralise wall-clock rules, guard the bundled data |
| Replayable | Diff a new run against a recorded one | committed baseline plus explicit `--update-baseline` |

---

## 3. How a row runs

The mechanism that makes this affordable, verified working:

1. **Train one golden user** with real logins. The engine short-circuits to a cautious
   level until `MIN_AUTH_EVENTS` (4) completed logins exist, so rows before that read
   identically whatever signals they send. Five logins opens the gate; seven or eight
   gives a stable Risk 1. Costs about 25 seconds, once per run.
2. **Per row, clone that profile** onto a fresh user by copying its `auth_process`
   rows in SQL, rewriting when they happened.
3. **One real login** with the row's delta applied.
4. **Harvest the verdict** from the engine's own `[RISK WHY]` log line, matched on
   user id.

About 2 seconds a row. Training per row instead would be roughly 30 minutes for the
full set.

Two details in step 2 are not optional:

- The copied rows are ones real logins produced, so every context hash is whatever
  the factories actually compute. Nothing is synthesised, so nothing can drift from
  the code that writes it.
- The timestamp must be rewritten **inside `auth_context_json`**, not only in
  `started_at`. `df_user` is assembled from that JSON and its embedded `event_time`
  is the only clock the time-based signals ever see. A verbatim copy reproduces the
  golden user's training burst inside a single minute, which reads as an unusual hour
  and an irregular gap on every row.

The explanation is harvested, never authored. Writing those strings by hand would
document a belief about the code rather than the code. It only works because
`[RISK WHY]` is a single log record; a multi-line block cannot be scraped reliably.

---

## 3a. The three sequence signals

Sixteen signals are properties of one login and are sent as a delta. Three are
properties of a sequence and cannot be expressed that way:

| Signal | Sequence | Result |
| --- | --- | --- |
| `concurrent_session` | logins from 2 other addresses, then the row's own | covered by `C01` |
| `recent_account_change` | the user changes their own password, then signs in | covered by `E01` |
| `login_failure` | failed logins first | not reachable, `F01` is a strict xfail |

These use real actions rather than the SQL clone. The clone exists because training 20
users through the browser would take half an hour, but the whole point of these three
rows is the path from a Keycloak event, through the SPI webhook, to what the engine
stores and reads back, and seeding the destination would skip exactly the part under
test. Three rows at a few seconds each is affordable.

Two findings came out of building them.

**An admin password reset does not drive `recent_account_change`.**
`AmfaWebhookEventListenerProvider.onEvent(AdminEvent, ..)` is an empty method, on the
stated grounds that AMFA only cares about end-user authentication events, and the realm
has `adminEventsEnabled: false` besides. Verified by resetting a password through the
admin API and finding no cache entry. So `E01` sets the UPDATE_PASSWORD required action
and lets the next login present the form, which is both what a real user does and the
only thing that works. The event that actually arrives on Keycloak 26 is
UPDATE_CREDENTIAL, not UPDATE_PASSWORD; both are forwarded and both are in the engine's
`ACCOUNT_ACTION_EVENT_TYPES`, and the artifact records which one it was.

**`C01` also trips `impossible_travel` and `time_interval`**, because logging in from
two cities seconds apart is exactly that. Left as is rather than engineered away: it is
real behaviour, the arithmetic check validates whatever fired, and it makes `C01` the
only row that covers `impossible_travel`.

The thresholds each row has to cross are read from the running engine rather than
copied, so a deployment with different values is still crossed rather than silently
missed. Each choreography also verifies its own outcome before the row's login runs, so
a sequence that did not take effect fails as "the setup did not happen" rather than as
a puzzling risk level, and records what it established in the artifact.

---

## 4. Determinism guards

Every item here is a failure mode already hit while building the harness.

**Throwaway realm per run.** Clone `test-amfa-realm.json` under a per-run name, run
there, delete it afterwards. This removes the whole class of "the suite mutated shared
state". The alternative, snapshot and restore, is error prone: one admin PUT
**replaces** the realm attribute map rather than merging it, and a PUT that omitted
the AMFA attributes wiped `fallbackRisk` and broke every login in the realm.

Two things the import needs, both found by hitting them. The export carries 175
internal `id` and `containerId` values belonging to the realm it came from, and those
are unique across the whole Keycloak instance, so importing a copy while the original
exists fails with a bare `Duplicate resource error` naming nothing; they are stripped
so Keycloak mints new ones. And `sslRequired` is set to `none` on the clone, because
Keycloak refuses plaintext HTTP once the client address is public and the geo rows
depend on public addresses.

**The suite owns its scoring parameters.** Not a preference. A realm with no parameters
of its own falls back to `default`/`default`, and `DEFAULT_DECISION_PARAMS` ships with
all nineteen signals `disabled: True`, so an inherited configuration would produce a
matrix where nothing ever fires and every row reads the same. `matrix_env.py` writes a
deliberate 1/2/3 weight spread plus the allow and deny entries the override rows need,
so the expected levels are determined by that file rather than by whatever was last
edited in a database.

**The scoring mode has to be pinned after the parameters are written.** Writing the
parameter set replaces the `__meta` that holds the per-realm scoring config, and the
deployment default is `bayesian`, so a run would otherwise score against a different
model than the baseline it is compared against. The suite pins `weight` and reads the
mode back rather than assuming the write took.

**Neutralise wall-clock rules.** The shipped realm sets `date_time` `allow=['09:00-05:00']`
and `deny=['10:00-11:30']`. Run at 10:30 and rows behave differently than at 14:00.
Fix the windows in the throwaway realm and test them with explicit rows instead.

**Seed at the current hour.** `date_time` scores the current hour against the hours in
history, so history seeded at "now minus N days" is wall-clock independent by
construction.

**Assert the bundled IP data has not moved.** Rows assert "this address is KR". DB-IP
Lite refreshes monthly and an address can be reassigned. Resolve every IP the matrix
uses during setup and fail with a clear message if a country changed, rather than
letting it surface as a confusing row failure.

**Fingerprint the configuration and refuse to run on a mismatch.** Expected levels
depend on per-signal weights, `WEIGHT_RISK_BANDS`, `MIN_AUTH_EVENTS`, the `HAZARD_*`
thresholds and the scoring mode. Record a hash of those in the artifact. If the live
config differs from the baseline's, stop and say so, or a single weight change looks
like twenty broken rows.

**Serial by necessity.** One shared Mailpit mailbox, one engine log stream, and a
per-user distributed lock. Parallelising would need per-recipient mailbox filtering
and is not worth it at 2 seconds a row.

**Guard the stack rather than assume it.** Preflight: containers up, `/health` ok with
`ip_data: ok`, Mailpit reachable, `KC_PROXY_HEADERS` set, SPI jar present and not
older than its source. That last check matters because
`docker compose up --force-recreate` rebuilds a container from its image and silently
discards anything `docker cp`'d into it, which produced a false negative when
verifying uncommitted code. For testing uncommitted engine code use `docker cp`
followed by `docker restart`, which keeps the writable layer.

---

## 5. Prerequisites the suite must set up

- **`KC_PROXY_HEADERS: xforwarded`** via `config/keycloak/docker-compose.e2e.yml`.
  Six of the 19 signals are derived from the client IP (`ip_address`, `country_name`,
  `geo_loc`, `anonymous_detection`, `impossible_travel`,
  `geolocation_cluster_label`), so driving them means choosing the IP Keycloak
  reports. The base compose deliberately leaves this unset, because trusting a
  forwarded address with no proxy in front lets any client pick the IP its own risk is
  evaluated against, and the shipped realm allow-lists `10.0.0.6`.
- **`sslRequired` relaxed** in the throwaway realm. Keycloak refuses plaintext HTTP
  once the client IP is public, returning `error="ssl_required"`.
- **Users need an email address.** Untrained users are Risk 3, which demands a step-up,
  and the email factor is the one a test can complete via Mailpit.

---

## 6. Baseline and drift

Built, in `matrix_baseline.py`. Each run writes `artifacts/signal-matrix.json` and
compares it against the committed `baselines/signal-matrix.json`:

| Change | Result |
| --- | --- |
| Risk level differs | **fail** |
| A login stopped completing, or started | **fail** |
| Same level by a different rule | warn |
| Different set of signals fired | warn |
| Reworded reasoning | warn |
| Row added or removed | warn |

This is what actually checks the 13 rows with no `expect`: their level depends on a
familiarity value that moves with the seeded history, so without the baseline they
would keep passing while the engine decided something different.

`login_completed` is a failure rather than a warning, which the original plan did not
say. Rows exist where the expected outcome is completion and rows where it is
rejection, so either flipping is a change in what a user experiences, exactly like the
level.

`--update-baseline` re-records both files and prints what it is accepting, so an
intentional change arrives as a reviewable diff. It is a flag and never a default: a
suite that quietly rewrites its own expectations reports every regression as a pass.

Two things were needed to make the comparison mean anything.

**Order had to be normalised, wording not.** The engine builds its changed-signal list
from a set, so the order varies between two runs of identical code. Measured across two
runs: 7 of the 19 rows differed that way. Compared verbatim, every run would report
seven wording changes and a real one would hide among them. `normalise_why` reorders
only the listed names, reproducing what the engine would have emitted had its set
iterated in sorted order, so a genuine message change still shows.

**Per-run values are not recorded.** The realm name carries a fresh uuid by design.
Recording it would put a guaranteed change in every regeneration and bury the real
ones, so the baseline keeps only the compared fields.

The fingerprint is checked in the session fixture, before the 25 seconds of training
and before any row runs, and aborts via `pytest.exit` rather than failing. Failing a
session-scoped fixture is reported once per test that requested it, so the first
version printed the same configuration message twenty times, which is the noise the
guard exists to prevent. The throwaway realm is still torn down on that path, verified.

The comparator has its own unit tests in `tests/unit/utils/test_matrix_baseline.py`,
24 of them, because its worst failure mode is silent: a comparator that reports "no
drift" when a level has moved makes the whole suite pass forever while checking
nothing, and that is invisible in a green run. The end-to-end behaviour was also
verified directly by tampering with the committed baseline and confirming the run
failed with the right two failures and one warning.

---

## 7. Layout and invocation

```
tests/e2e/
  matrix_lib.py            # login driver, profile cloning, verdict harvesting
  matrix_env.py            # throwaway realm, preflight, scoring params, fingerprint
  matrix_rows.py           # rows as data: {id, delta, seed, expect, note}
  matrix_baseline.py       # normalising, comparing, recording
  matrix_choreography.py   # the sequences the three non-single-login signals need
  test_signal_matrix.py    # pytest, one parametrized case per row
  baselines/
    signal-matrix.json     # committed, the run to compare against
    signal-matrix.md       # committed, human-readable, reviewable
  artifacts/               # gitignored, current run
```

```bash
# the full set, compared against the committed baseline
PYTHONPATH=. python3 -m pytest tests/e2e/test_signal_matrix.py

# accept intentional changes, then commit the diff
PYTHONPATH=. python3 -m pytest tests/e2e/test_signal_matrix.py --update-baseline
```

A `-k` filter is allowed but skips the baseline comparison rather than comparing a
subset, because "no drift" across 3 of 20 rows would read as a clean run.

Rows are data so adding one is a dict rather than a function, and pytest
parametrisation gives per-row pass and fail instead of one monolithic result.

| Mode | Rows | Time |
| --- | --- | --- |
| full | 23 | ~41s measured |
| chrome | N | +15s a row, not built |

The choreographed rows are what took it from 15s to 41s: each performs several real
logins before its own, which is the cost of driving a sequence rather than seeding it.

The HTTP driver uses the same Keycloak forms, cookies and SPI as a browser, with
nothing mocked, and that claim has now been checked rather than asserted.
`test_browser_journeys.py` runs the same login both ways and compares the engine's verdict, automatically (B11).

Verified: a real Chromium login and the driver, given the same presented context and
twin users with the same seeded history, both reached Risk 3 with the same five signals
and byte-identical reasoning.

Two details make it honest. The driver is fed what the browser actually presented rather
than the matrix baseline, because a real browser genuinely is a different device from the
seeded history and comparing against the baseline would show a true difference as though
it were driver infidelity. And neither half sends `X-Forwarded-For`, since a browser
cannot, so both fall back to the socket address; that is the only address they can agree
on, and it means the geo rows are outside what this can compare.

This was originally a manual three-command tool, `chrome_spotcheck.py`, on the grounds that automating it meant a browser dependency for a check that only needed running when the login flow changed. The browser suite took that dependency for other reasons, so the check is now automated and the manual tool has been removed.

---

## 8. Known limits

- **Needs the live stack.** This complements the unit suite rather than replacing it.
  Per-signal scoring logic belongs in `tests/unit`; this covers the wiring across the
  three repositories.
- **Single-signal isolation is not reachable through the front door.**
  `event_cluster_label`, weight 3, fires on essentially any context change because it
  clusters the whole context vector, so a "browser only" delta is really browser plus
  cluster. Rows are therefore honest delta sets, with the reported signal list showing
  what actually fired. A second tier that temporarily disables that signal would give
  per-signal weights; deferred pending a decision.
- **`login_failure` cannot fire from real behaviour, so its row is a strict xfail.**
  The signal scores `auth_process` rows with `final_status='LOGIN_ERROR'`, and neither
  failure a user can produce creates one. A wrong password does emit Keycloak's
  LOGIN_ERROR event, but the adaptive authenticator runs after the password form, so no
  auth process is open and `AuthEventService.__finalize_process` discards it: measured,
  45 such events, every one with a null `auth_process`, and no `auth_process` row at
  all. A wrong emailed code does happen inside an open process, but Keycloak emits no
  event for it: measured, zero `auth_event` rows for a user who failed five. So the
  four patterns the check implements, failure rate, distributed brute force, activity
  burst and bot-like regularity, cannot see password guessing, which is what they
  describe. The pre-existing `LOGIN_ERROR` rows in the dev database appear to come from
  a stale cached process being finalised by a later, unrelated failure, which would
  attribute the failure to the wrong login. `F01` is kept and marked
  `xfail(strict=True)` so that fixing the wiring forces the mark off rather than
  leaving a row that silently proves nothing. Fixing it is a product decision, either
  scoring `auth_event` instead or emitting an event on a failed step-up, so it is
  flagged rather than changed here.
- **The hazard floor is not reachable through the front door.** It was written for the
  case where many signals move while the device stays familiar, so familiarity would
  otherwise subtract from the escalation. Reaching it needs 6 or more changed signals
  *and* a high device/network familiarity, and those conflict: familiarity is computed
  over the device *and* the network, and there are not 6 signals that can move without
  the network being one of them. `A02` gets as close as the design allows, tripping
  hazard on Tor plus an unusual hour with every device field identical, and no
  familiarity adjustment follows at all. The floor is therefore covered only by
  `tests/unit/services/test_hazard_floor.py`, 10 tests, which is stated here so nobody
  reads the green matrix as evidence for it.
- **Risk 4 is not a rejection in the shipped realm.** The deny-list rows assert that
  the engine forces Risk 4, and it does. But the realm's flow has only two risk
  conditions, `risk-2-EQUAL` and `risk-3-GREATER_OR_EQUAL`, so Risk 4 falls into the
  `>= 3` branch and gets the same email code as Risk 3: `D01`, `D02` and `G03` all
  complete their logins. End to end the "hard override to the rejection level" is
  currently indistinguishable from an ordinary step-up. The engine side is right; the
  realm has no branch that denies. Worth a decision separately from this suite, and
  the baseline records the completion so a future fix shows up as a diff.

---

## 9. Sequencing

| Step | Work | State |
| --- | --- | --- |
| 1 | Throwaway realm, preflight guards, teardown | done |
| 2 | Row definitions: baseline, single delta, band boundaries, overrides, gate | done |
| 3 | Artifact writer, baseline diff, `--update-baseline` | done |
| 4 | The three choreographed signals | done: 2 covered, 1 xfail |
| 5 | Chrome spot-check mode, README | done |

Steps 1 to 3 were the useful unit: a replayable matrix with drift detection, which is
now in place.

---

## 10. Decisions taken

- Designed matrix, not a cartesian product.
- Weight mode only for now. Bayesian would need its own baseline.
- Time-dependent signals are seeded rather than waited for.
- Throwaway realm per run rather than mutating `test-amfa`.
- A risk-level change fails the run; an explanation change warns.

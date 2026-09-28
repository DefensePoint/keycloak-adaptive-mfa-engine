# Functional test coverage: what exists, and what to add

Companion to [signal-matrix-plan.md](signal-matrix-plan.md), which describes the harness.
This one is about *coverage*: what the functional suite proves today, where the holes
are, and a named test case for each one.

Every proposed case has an id and a title, so it can be referenced in a commit, a review
or a bug report without re-describing it. Ids continue the matrix scheme, one letter per
family.

**Status:** complete, and four of the eight decisions are now taken and
implemented. The open ones are listed in the last section.

---

## 1. What exists today

| Layer | Where | Count | What it proves |
| --- | --- | --- | --- |
| Unit | `tests/unit/` | 499 | Per-signal scoring logic, in isolation, no stack |
| Signal matrix | `tests/e2e/test_signal_matrix.py` | 23 rows (1 xfail) | Each signal end to end through a real login, plus the scoring arithmetic and the documented rules |
| Baseline drift | `tests/e2e/baselines/` + `matrix_baseline.py` | 24 unit tests | A level that moves on a row that cannot assert one is caught |
| Scenario smoke | `tests/e2e/run_e2e.py` | 14 checks | The wiring across all three repos: SPI, engine, redis, postgres, webhook |
| Container-side | `test_signal_gating_e2e.py`, `test_inactive_days_e2e.py` | 7 | Per-realm signal gating and the inactive-days threshold, against real redis/postgres |
| Driver fidelity | `test_browser_journeys.py` (B11) | automatic | The HTTP driver reaches the same decision as a real browser |

### Signal coverage, measured from the committed baseline

17 of 19 signals fire in at least one row. The exceptions:

| Signal | State | Why |
| --- | --- | --- |
| `client` | never fires | No row signs in to a second client |
| `login_failure` | never fires | Not reachable at all, `F01` is a strict xfail |
| `geo_loc` | disabled | Switched off in the matrix parameter set |

Three more fire only as a **side effect** of another row rather than being driven
deliberately, so nothing would notice if they silently stopped: `impossible_travel` and
`time_interval` (both incidental to `C01`), and `inactive_account` (only `S10`).

---

## 2. The holes, in priority order

| # | Hole | Risk if left |
| --- | --- | --- |
| 1 | ~~Bayesian scoring is entirely uncovered~~ | **Closed.** Covered by `test_bayesian_matrix.py`, which found three mechanisms that do not run in that mode |
| 2 | No coverage of the **credibility bands**, the decay, or the gate at their boundaries | Off-by-one in a band moves every user one level |
| 3 | **Failure modes are untested**: engine down, engine slow, redis down | The fallback path runs only in incidents, which is the worst time to find it broken |
| 4 | **Step-up completion is only proven for email** | The TOTP tier could break unnoticed |
| 5 | Signals that fire only incidentally, or not at all | A signal can stop working silently |
| 6 | Per-signal weights are unverifiable because `event_cluster_label` fires on any change | The weight table is asserted only in aggregate |

---

## 3. Proposed test cases

Legend: **Ready** to write now, **Blocked** on a decision, **Needs** a harness addition.

### Y — Bayesian mode

Implemented in `test_bayesian_matrix.py`: the same rows, its own realm, its own
committed baseline in `baselines/signal-matrix-bayesian.json`. A separate module rather
than a parameter on the existing matrix, because the levels are not comparable between
modes and weight mode should not get slower for everyone.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| Y01 | Bayesian: a quiet trained login stays at the lowest level | The mode works at all | **Done** |
| Y02 | Bayesian: every row is recorded against its own baseline | 20 rows, the only check most of them can have | **Done** |
| Y03 | The pinned scoring mode survives a parameter rewrite | A regression guard: a rewrite must not reorder-and-flip the pinned mode | **Done** |
| Y04 | A login where many signals change is challenged in both modes | The property hazard exists to guarantee, asserted where the mechanism is absent | **Done** |
| Y05 | Bayesian: a denylisted address still forces the rejection level | Hard overrides are mode-independent | **Done** |
| Y06 | Bayesian: the history gate short-circuits before scoring | Gated rows report `history-gate`, not the scorer | **Done** |
| Y07 | The two modes are compared row by row and the differences recorded | 13 of 21 shared rows differ | **Done** |
| Y08 | The mechanisms absent from bayesian scoring are recorded | Asserts the absence, so a later change is caught | **Done** |

**What Y found.** `__evaluate_risk` returns from the bayesian branch before reaching
hazard activation, the drop-down decay and `_adjust_for_credibility`, so three
mechanisms that shape a weight-mode decision do not run in the deployment default.
Credibility is not lost, it becomes a model feature and shows up in the explanation as
"device / network familiarity", but hazard and decay simply do not happen. On every
takeover-shaped row measured the model reaches Risk 4 anyway, which is more severe than
the hazard floor would have been, so nothing is currently worse off. That is a fact
about today's calibration rather than a guarantee, which is why Y04 asserts the floor
as a property instead of trusting it.

**The difference worth a decision.** `E01`, a login straight after the user changes
their own password, is Risk 2 in weight mode and **Risk 1 in bayesian**, meaning no
challenge at all. The model puts it at 2%: `recent_account_change` is the only signal
raising risk, and a familiar device, network, OS and language outweigh it. This is
arguably within design, since `process_account_action`'s own docstring says the signal
should "combine with unfamiliar-device / new-network signals rather than hard-blocking
on its own", but it is worth confirming that a credential change followed immediately
by a sign-in deserves no step-up in the default mode.

**One row cannot run here.** `C01` establishes its setup by completing logins from other
addresses. Weight mode scores those at Risk 3 and asks for an emailed code the harness
can answer; bayesian scores them at Risk 2 and asks for TOTP, which these users have not
enrolled. Skipped with that reason, and reachable once T02 adds TOTP enrolment.

### K — Credibility and familiarity bands

Boundaries are 0.3, 0.6 and 0.85. Each needs a seeded history that lands the value on a
chosen side of a boundary, which is a new harness capability.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
In `test_familiarity_bands.py`. Two of the four bands turned out to be unreachable, and
finding out why is the main result of this family.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| K01 | An unfamiliar network raises the level | The `c < 0.3` branch, the only one doing work today | **Done** |
| K02 | A familiar network leaves the score alone | The `0.3 <= c < 0.6` branch, and the other side of K01's boundary | **Done** |
| K03/K04 | A familiar device can lower the level | **xfail:** neither lowering band is reachable | **Found** |
| K06 | An allowlisted attribute suppresses the unfamiliar raise | The `whitelisted_vars` guard | **Done** |
| K07 | Device credibility never leaves its prior | The measurement the xfails rest on, pinned | **Done** |

**Device credibility never rises above its 0.2 prior.** Measured on a user whose four
history rows carry exactly the device hash of the login being scored, the engine logs
`Evaluating device credibility. Number of successes 0 | failures 0 | history 0`, while
the network half of the same login logs `successes 4 | failures 0 | history 4`. The
cause is visible in the hashes: one login computes two different device hashes for a
single context, stores one and looks up credibility with the other, so no history row
ever matches. The network hash matches exactly and its credibility works.

Since `c = 0.55*device + 0.45*network` and device is pinned at 0.2, the highest
reachable value is **0.56**, below the 0.6 boundary. So the familiarity adjustment can
only ever raise risk, never lower it, and a returning user on a known device gets no
benefit from being recognised.

That also settles K05. The hazard floor exists to stop familiarity undoing a hazard
escalation; since familiarity cannot lower anything, the floor guards a branch no login
reaches. Correct code, currently unreachable, and covered by unit tests only.

One detail worth knowing for anyone writing more of these: the engine only names
familiarity in its explanation when the adjustment *moves* the level. The middle band
is silent, so these tests read the two values from the engine's debug log instead.

### N — Drop-down decay

`DROP_DOWN_DECAY_DAYS=30`, `DROP_DOWN_DECAY_STEPS=2`. Entirely untested end to end.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
In `test_history_rules.py`. These need a realm with `time_interval` disabled: the decay
only runs when *nothing* changed, and a 36-day silence is itself a changed signal, so
without that the login takes the scoring path and the decay is never reached.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| N01 | A long absence relaxes by the configured number of steps | Risk 3 to Risk 1 after 36 quiet days | **Done** |
| N02 | A clean login relaxes one level below the last decision | The control: without it, "two steps" is unfalsifiable | **Done** |
| N03 | The decay never takes a level below the minimum | The `max()` floor | **Done** |
| N03b | A login already at the minimum says so | The message that distinguishes "nothing to do" from "did not run" | **Done** |

### Q — History gate boundaries

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| Q01 | One login short of the threshold still reads the gate | The boundary from below | **Done** |
| Q02 | Exactly the threshold is scored rather than gated | The boundary from above | **Done** |
| Q03 | The gate returns the configured default level | **Open question:** the gate returns Risk 3 while `DEFAULT_RISK_LEVEL` is 2. Resolve before asserting | Blocked |

### T — Step-up factors and outcomes

| Id | Title | Proves | State |
| --- | --- | --- | --- |
In `test_step_up_factors.py`. The level is pinned with the realm's *fallback*, by
pointing it at an unreachable engine, rather than by engineering a score: the question
here is what a level asks for, not how a login reaches it, so these keep working if the
scoring changes.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| T01 | The lowest level asks for nothing beyond the password | The quiet path is quiet | **Done** |
| T02 | The TOTP tier completes with an enrolled authenticator | The one factor never completed anywhere | **Done** |
| T02b | A user without an authenticator is asked to enrol and may proceed | What Risk 2 really does | **Found** |
| T03 | The email tier completes with a mailed code | Asserted directly, once | **Done** |
| T04 | The rejection level does not let the login through | An `AMFA Deny` subflow now refuses at risk >= 4 | **Fixed** |
| T05 | A wrong emailed code does not complete the login | The challenge is a gate, not a formality | **Done** |
| T06 | An emailed code cannot be used for a second login | Single use | **Done** |

T07, the code's expiry, was not written: it would need a test that waits out the
lifetime, and T06 already shows a code is consumed.

**T02b is the finding.** The matrix records Risk 2 logins as not completing, but that
was the harness being unable to answer the form. The realm's Risk 2 branch offers
*enrolment* to a user with no authenticator, and enrolling satisfies the step-up in the
same session. It is the standard Keycloak conditional-factor pattern, and it means the
second factor adds nothing against someone who has the password and reaches an
unenrolled account first. Whether that is acceptable depends on how accounts are
provisioned, so the test states the behaviour rather than asserting against it.

Enrolment is opt-in in the driver (`allow_totp_enrolment`, default off) precisely
because turning it on changes what every Risk 2 row measures, and would silently
rewrite the committed baselines.

### R — Resilience and failure modes

Implemented in `test_resilience.py`. Failure is simulated by pointing a *throwaway
realm's* `adaptiveAuthEndpoint` at an address that fails in a chosen way, so the shared
engine is never stopped or paused and the tests are safe to run against a stack someone
else is using. The level is observed from the step-up the login is actually presented
with, not from a log, so each assertion is about what a user experiences.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| R01 | A login completes at the fallback level when the engine is unreachable | The realm's `fallbackRisk`, the most important failure path | **Done**, 3 levels |
| R02 | A login completes at the fallback level when the engine returns an error | Distinct from unreachable: a non-2xx must not become a decision | **Done**, 3 levels |
| R03 | A login survives an engine that never answers | The timeout path: dropped packets, not a refused connection | **Done** |
| R03b | A login is not held for minutes by an unresponsive engine | 16s, after a 5s timeout was added to all three engine calls | **Fixed** |
| R04 | A realm with no `fallbackRisk` attribute still lets people log in | The guard from `fix/guard-realm-attributes` | **Done** |
| R05 | An unusable `fallbackRisk` setting falls back to a challenge | A typo must not be what removes the step-up. 4 shapes | **Done** |

R01 and R02 are parametrized across all three usable fallback levels rather than one,
because the claim worth testing is not "it falls back" but "it falls back to the level
the realm asked for"; a fallback that ignored the attribute would pass a single-level
test.

Two items from the original plan were dropped rather than written. Redis unavailability
would mean pausing a shared container, which breaks the isolation every other test here
maintains, and the missing-IP-data case is better as a unit test of `health_route` than
as an e2e test that has to damage a running engine. Both are noted here so the omission
is deliberate rather than forgotten.

### P — Parameters and per-realm configuration

| Id | Title | Proves | State |
| --- | --- | --- | --- |
In `test_realm_parameters.py`. `matrix_params` now takes overrides, so a test states
only its difference from the matrix set. `disabled` adds to the default set rather than
replacing it: the first version replaced it, and a test switching off
`event_cluster_label` silently switched `geo_loc` back on.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| P01 | One changed field is one changed signal when the cluster is off | Unlocks the M family | **Done** |
| P02 | A disabled signal does not fire even when its condition is met | e2e counterpart to the container-side test | **Done** |
| P03 | A realm with no parameters of its own scores nothing | The shipped defaults disable everything | **Done** |
| P05 | A denylisted address beats an allowlisted one | Precedence, and the tempering | **Done** |
| P06 | The dormancy threshold is honoured per realm, both sides | A per-realm value changing a real decision | **Done** |

P04 was dropped as redundant: P03 and P06 already show two realms with different
parameters reaching different answers, which is the claim it was written for.

**P05 documented behaviour worth knowing.** When an address is on both lists the
denylist wins, but the level is *tempered to a Risk 3 floor* rather than the Risk 4 an
uncontested denylist forces. So an allow entry softens a block without cancelling it.
Deliberate and explained in the engine's own output; asserted here so a change in either
direction has to edit the test.

### M — Weight band boundaries

All require P01, and become trivial once it exists.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| M01 | A weight sum lands in the documented band | Sums of 1 and 2 both give Risk 1 | **Done** |

M02 to M04 were not written. Sums that land exactly on 3 or 6 need several signals at
once, and those also move the familiarity value, which adjusts the level afterwards, so
the reading would not be a clean test of the band. The matrix's per-row arithmetic check
covers those sums in aggregate.

### X — Signals not driven deliberately

| Id | Title | Proves | State |
| --- | --- | --- | --- |
In `test_history_rules.py`, except X02 which needs a parameter change and lives in
`test_realm_parameters.py`.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| X01 | Signing in to a different client fires the `client` signal | The one signal no row touches | **Done** |
| X02 | Enabling `geo_loc` makes a moved location contribute | **xfail:** the parameter is dead | **Found** |
| X03 | Impossible travel is driven deliberately | Two cities minutes apart, on purpose | **Done** |
| X04 | An unusual gap between logins fires the time-interval signal | Needs two prior logins, measured | **Done** |
| X05 | Failed password attempts raise the failure signal | **Blocked** on the `login_failure` wiring decision | Blocked |
| X06 | Dormancy is asserted near its threshold | 44 and 36 days against a 40-day line | **Done** |

**X02 found a dead parameter.** `geo_loc` ships in `DEFAULT_DECISION_PARAMS` with weight
3, is exposed for configuration, and is never evaluated: `eval_risk.py` computes each
signal behind an explicit `if "<name>" in enabled_params` block and there is no such
block for it. Grepping the engine finds the name in exactly one place, its own default
entry. Enabling it does nothing, silently. Either implement the signal or drop the
parameter; if it is dropped, delete the test rather than unmarking it.

**X04 needed two prior logins, not one.** The check calls the most recent interval
FORBIDDEN when it is below the *median* of all intervals, so one extra login left the
median dominated by day-long gaps and read ACCEPTABLE. The assertion is on the signal
rather than the level, because `time_interval` carries weight 1 and fires without moving
the level at all.

### V — Input validation and the API surface

Implemented in `test_engine_api.py`, going at `/decision` directly, because the
interesting cases are the ones a login cannot produce.

| Id | Title | Proves | State |
| --- | --- | --- | --- |
| V01 | A malformed decision request is refused rather than scored | Unusable input must not produce a level. 6 shapes | **Done** |
| V02 | A decision requires a valid token | The endpoint is not public. 3 shapes | **Done** |
| V03 | A token from one realm cannot score a login in another | Tenant isolation, which the per-realm model rests on | **Done** |
| V04 | A user with no history is scored cautiously | The cold-start path every user takes once | **Done** |
| V05 | A request the engine cannot store returns the configured fallback | Two routes; the environment is authoritative | **Done** |
| V05b | A failed evaluation does not silently succeed | The fallback is distinguishable from a real decision | **Done** |
| V06 | The engine fallback level is pinned so a change is visible | A change to the value stays visible | **Done** |

---

## 4. Totals and sequencing

| Family | Cases | Ready | Needs harness | Blocked |
| --- | --- | --- | --- | --- |
| Y Bayesian | 8 | done | | |
| K Credibility | 7 | 1 | 5 | 1 |
| N Decay | 4 | 4 | | |
| Q Gate | 3 | 2 | | 1 |
| T Step-up | 7 | 5 | 1 | 1 |
| R Resilience | 6 | 6 | | |
| P Parameters | 6 | 5 | 1 | |
| M Bands | 4 | | 4 | |
| X Signals | 6 | 5 | | 1 |
| V Validation | 4 | 4 | | |
| **Total** | **58** | **all implemented** | | **7 decisions** |

Suggested order, each step useful on its own:

1. **R** and **V**. No new harness, and the failure paths are the ones that matter most
   in production. Fastest value.
2. ~~**Y**~~. Done.
3. **X**, **P**, **N**, **Q**. Fill in the signals and rules with what the harness
   already does.
4. **P01**, then **M**. Per-signal weights become verifiable.
5. ~~**K**~~. Done, and it found that two of the four bands cannot be reached.
6. ~~**T02**~~. Done; the harness can enrol an authenticator.

## 5. The four blocked cases

None is a test problem; each needs a decision first.

### Taken and implemented

| Case | Decision | What changed |
| --- | --- | --- |
| V05 | An unstorable request must fail, not fabricate a verdict | Reversed from "the environment is authoritative for `FALLBACK_RISK_LEVEL`": that design let a malformed field turn a real Risk 4 (deny) into a fake Risk 1 (no challenge). The test now asserts a server error with no `riskLevel`, never HTTP 200 |
| R03b | 5 second timeout | Applied to all three engine calls in the SPI. A blackholed engine now holds a login 16s, measured, against 150-225s before |
| T04 | Risk 4 should deny | An `AMFA Deny` subflow, conditional on risk >= 4, at priority 24 ahead of both step-up branches |
| T02b | Leave as is for now | No change |

### Still open

| Case | Decision needed |
| --- | --- |
| X05 | Should `login_failure` score `auth_event` rather than `auth_process`, or should a failed step-up emit an event? |
| K05 | Follows from K03: the hazard floor guards the lowering branch, so it becomes reachable if K03 is fixed |
| Q03 | Why does the gate return Risk 3 when `DEFAULT_RISK_LEVEL` is 2? |
| Y-E01 | Should a login immediately after a credential change be challenged in bayesian mode? It is Risk 1 today, and Risk 2 under weight scoring |
| X02 | Implement `geo_loc` or remove it? It is configurable, weighted, and never evaluated |
| K03 | Where should the screen resolution be normalised? `/auth_context` hashes the raw value and `/decision` hashes the normalised one, so the two device hashes disagree for any resolution not already canonical |

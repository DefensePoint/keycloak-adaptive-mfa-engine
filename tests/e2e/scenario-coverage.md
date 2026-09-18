# AMFA scenario coverage

Where each behaviour of the system is exercised: the engine **unit** suite
(`tests/unit`, logic in isolation) versus the **E2E** suite (`run_e2e.py`, live
wiring across Keycloak + engine + redis/postgres + MFA). "Live-observed" means
the behaviour is visible in engine logs during an E2E login even if not asserted
directly.

## Covered

| Scenario | Unit | E2E | Notes |
| --- | :---: | :---: | --- |
| Engine auth enforced (no / bad token) | — | ✅ | `sc_engine_rejects_no_token` (401) |
| `/auth_context` + `/decision` happy path | ✅ `tests/unit/api` | ✅ | `sc_engine_decision_new_user` returns riskLevel 1..4 |
| Full browser-flow login chain (SPI → engine → webhook → `auth_event`) | — | ✅ | `sc_login_stepup_and_complete`; asserts step-up, completion, webhook 200, event recorded |
| Risk-tiered MFA routing (2 → TOTP, 3+ → Email) | — | ✅ | step-up factor asserted; email completed via Mailpit, TOTP with `E2E_TOTP_SECRET` |
| Wrong password rejected / failure path | ✅ `test_login_failure` | ✅ | `sc_login_wrong_password` |
| Blacklist override forces elevated risk | ✅ (params) | ✅ | `sc_blacklist_override`: a blacklisted IP scores >= clean IP and >= 3. The override actually forces Risk 4 as a hard block, so the assertion is looser than the behaviour |
| Recent account-change escalation (E4) | ✅ `account_action` | ✅ | `sc_e4_account_change`: seed the account-change event, then a login surfaces `recent_account_change=SUSPICIOUS` |
| Per-realm signal disable is honored | ✅ `test_signal_gating_e2e` | ✅ | Fixed in `fix/signal-gating`: `__param_is_enabled` now checks membership in `decision_params`. `sc_disabled_signal_does_not_fire` (live) disables `recent_account_change`, seeds the event, and asserts it does NOT fire; `test_signal_gating_e2e.py` (hermetic, real postgres+redis) asserts disabled signals are stripped and gate off while enabled ones gate on. Also covers `login_failure`/`concurrent_session`, now gated by `decision_params` too (Option B). |
| Weight aggregation, cumulative bands (A3) | ✅ `test_decision_a3_partial_decisions` | live-observed | log: `Partial decision cumulative_weight=… bands=(3,6)` |
| Hazard thresholds (A4) | ✅ `test_decision_a4_hazard_threshold` | live-observed | gate vs partial path |
| Impossible travel + speed cap (A1) | ✅ `test_impossible_travel` (12) | live-observed | `impossible_travel` in `risk_eval_vars` |
| Credibility adjustment | ✅ (decision) | live-observed | log: `credibility of 0.56` |
| Drop-down time decay (B6) | ✅ `test_decision_b6_integration`, `test_decision_drop_down` | — | needs a time gap between logins |
| Scoring modes weight vs bayesian | ✅ `test_scoring_config_schema` + decision | partial | realm uses weight; bayesian is the env default |

## Not yet in the E2E suite (logic is unit-tested; wiring is not)

| Scenario | Unit | Why not E2E yet / how to add |
| --- | :---: | --- |
| Login-failure patterns (E3: rate, distributed, bot-timing, burst) | ✅ `test_login_failure` | needs many seeded `LOGIN_ERROR` events in redis; add a scenario that drives N bad logins then one good |
| Concurrent-session detection (E2) | ✅ `checks` | needs logins from several distinct IPs in a window; not reproducible from one host without IP spoofing |
| Whitelist override (risk suppression) | ✅ (params) | the blacklist path is covered; the whitelist counterpart could be added the same way |
| Risk-1 no-step-up (fully familiar context) | ✅ (drop_down) | hard to force deterministically because history evolves each login |

## Known gaps (product scope, not test gaps)

- **SSO / brokered (IdP) logins are not risk-scored.** They bypass the forms
  subflow where the Auth Context / Adaptive Auth authenticators run. Deferred.
- **Organization changes are not monitored.** They arrive as admin events; the
  listener's `onEvent(AdminEvent)` is a no-op. Deferred.

## Recommended next additions (highest value first)

1. **Login-failure / concurrent-session E2E** — drive N failed logins (or logins
   from several IPs) and assert the E3/E2 signals fire. Needs seeded redis state.
2. **TOTP-tier completion by default** — provide `E2E_TOTP_SECRET` (or seed a
   known secret in the test realm) so the TOTP step-up path is completed on
   every run, not only when the email tier is chosen.
3. **Whitelist override E2E** — mirror `sc_blacklist_override` for the
   risk-suppressing whitelist path.

"""The risk-signal matrix, run as one pytest case per row.

Each row is a real login against the live stack with a chosen context, and the
assertions are made against the engine's own account of its decision rather than
against a level someone typed into a table.

Three checks per row, in increasing strength:

**The decision happened.** A row that produced no verdict is a broken row, not a
passing one. Without this an outage would look like a clean sheet.

**The arithmetic holds.** The weights of the signals the engine says changed must map
to the band it says it chose. This verifies the scoring on every row without anyone
predicting outcomes, and it uses the engine's own list, so a signal firing
unexpectedly is caught rather than assumed away.

**The documented rules hold.** Rows where a rule fixes the answer regardless of score,
a deny-list match, a hazard escalation, the history gate, assert the level directly.

Levels that depend on the familiarity value are not hardcoded. They are recorded and
compared against the committed baseline in `baselines/signal-matrix.json`, which is
what catches a level moving on the 12 rows that cannot assert one directly. See
`matrix_baseline.py` for what fails and what only warns.

Run it:

    docker compose -f config/keycloak/docker-compose.yml \\
        -f config/keycloak/docker-compose.e2e.yml up -d
    PYTHONPATH=. python3 -m pytest tests/e2e/test_signal_matrix.py -v
"""

import json
import os
import pathlib

import pytest

from tests.e2e import matrix_baseline as base
from tests.e2e import matrix_choreography as choreo
from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib
from tests.e2e.matrix_rows import (
    IP_PALETTE,
    ROWS,
    expected_band,
    signals_from_why,
)

ARTIFACT_DIR = pathlib.Path(
    os.getenv("E2E_MATRIX_ARTIFACTS", pathlib.Path(__file__).parent / "artifacts")
)

# Filled by the row cases, written out at session end. Module level rather than a
# fixture because the writer runs after the last case has finished.
RESULTS: list[dict] = []


def env_min_auth_events() -> int:
    """How many completed logins the engine needs before it scores rather than gates."""
    return int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])


@pytest.fixture(scope="session")
def matrix(pytestconfig):
    """One isolated realm and one trained golden profile for the whole run.

    Session scoped because training is the expensive part: about 25 seconds once,
    against roughly 30 minutes if every row trained its own user. Rows clone this
    profile, so they stay independent of each other despite sharing it.
    """
    updating = pytestconfig.getoption("--update-baseline")

    with env.MatrixRun() as run:
        # Checked before any row runs, and before the 25 seconds of training, because
        # a changed weight moves most rows at once: comparing them in that state
        # produces nineteen failures that are all one configuration change. Skipped
        # when re-recording, since that is the way to accept the new configuration.
        recorded = base.load_baseline()
        if recorded and not updating:
            drift = base.fingerprint_drift(recorded, {"run": run.observed})
            if drift:
                # pytest.exit rather than pytest.fail: failing a session-scoped
                # fixture is reported once per test that requested it, so this
                # printed the same message twenty times, which is the exact noise
                # the guard exists to prevent. Raised inside the MatrixRun context,
                # so the throwaway realm is still torn down on the way out.
                pytest.exit(f"matrix not run: {drift}", returncode=1)
        env.verify_ip_palette(IP_PALETTE)

        # The login driver is module-level configured, so point it at this run's realm.
        original_realm = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)

            # Exactly enough real logins to clear the gate. Training stops there on
            # purpose: the next clean login decays from Risk 3 to Risk 2, and the
            # shipped realm asks for TOTP at Risk 2 while accepting an email code at
            # Risk 3, so a user with no authenticator cannot complete it and training
            # would deadlock. The clones supply the low-risk history instead.
            history = lib.train(
                lib.BASELINE_CONTEXT, username, golden_id,
                target=env_min_auth_events(),
            )
            trained = lib.completed_logins(golden_id)
            if trained < env_min_auth_events():
                pytest.fail(
                    f"golden profile reached only {trained} completed logins, below the "
                    f"{env_min_auth_events()} the history gate needs, so every row "
                    f"would read the gate rather than its own delta. "
                    f"Training detail: {history}"
                )

            probe = lib.run_row(token, golden_id, "probe", {})
            run.track(probe["user_id"])
            if probe["risk"] != 1 or probe["mode"] != "weight":
                pytest.fail(
                    f"a cloned profile did not produce a quiet baseline: got Risk "
                    f"{probe['risk']} in {probe['mode']} mode, expected Risk 1 in "
                    f"weight mode. Every row is measured against this, so the run "
                    f"would be meaningless.\n  why: {probe['why']}"
                )

            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original_realm


def _write_artifact(observed: dict) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run": {
            "config_fingerprint": observed.get("config_fingerprint"),
            "realm": observed.get("realm"),
            "scoring_mode": "weight",
            "engine_health": (observed.get("engine_health") or {}).get("status"),
            "ip_data": ((observed.get("engine_health") or {}).get("ip_data") or {}).get(
                "status"
            ),
        },
        "rows": RESULTS,
    }
    (ARTIFACT_DIR / "signal-matrix.json").write_text(json.dumps(payload, indent=1))

    lines = [
        "| Row | Delta | Risk | Rule | Signals the engine reported |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in RESULTS:
        lines.append(
            f"| {row['id']} | {row['delta'] or '(baseline)'} | {row['risk']} | "
            f"{row['rule']} | {', '.join(row['signals']) or 'none'} |"
        )
    (ARTIFACT_DIR / "signal-matrix.md").write_text("\n".join(lines) + "\n")
    return payload


def _as_param(row: dict):
    """A row as a pytest param, marked xfail if the signal cannot currently fire.

    strict=True on purpose: an xfail that starts passing fails the suite, so fixing
    the wiring forces the mark to be removed rather than leaving a row that silently
    proves nothing. `raises` is pinned too, so the row still fails loudly if it breaks
    for some unrelated reason.
    """
    marks = []
    if row.get("unreachable"):
        marks.append(pytest.mark.xfail(
            reason=row["unreachable"], strict=True,
            raises=choreo.ChoreographyError,
        ))
    return pytest.param(row, id=row["id"], marks=marks)


# Rows expected to fail never record a result, so the baseline comparison must not
# count them or it would skip itself, silently, on every run.
COMPARABLE_ROWS = [r for r in ROWS if not r.get("unreachable")]


@pytest.mark.parametrize("row", [_as_param(r) for r in ROWS])
def test_matrix_row(matrix, row):
    before = None
    if "choreograph" in row:
        name, args = row["choreograph"]
        before = choreo.BY_NAME[name](*args)

    result = lib.run_row(
        matrix["token"],
        matrix["golden_id"],
        row["id"],
        row["delta"],
        clone=not row.get("gate", False),
        before=before,
        **row.get("seed", {}),
    )
    matrix["run"].track(result["user_id"])

    why = result["why"]
    # Both of these are ordering fixes for the same underlying cause: the engine
    # derives its changed-signal list from a set, so the order varies between two runs
    # of identical code. Measured across two runs, 7 of the 19 rows differed that way.
    # Recorded raw, every run would report seven changes and a real one would hide
    # among them. normalise_why touches only the order of the listed names.
    signals = sorted(signals_from_why(why))
    why = base.normalise_why(why)
    rule = _classify(why)

    RESULTS.append({
        "id": row["id"],
        "delta": result["delta"],
        "risk": result["risk"],
        "rule": rule,
        "signals": signals,
        "mode": result["mode"],
        "step_up": result["steps"],
        "login_completed": result["login_ok"],
        "why": why,
        "note": row["note"],
        "choreography": result.get("choreography"),
    })

    assert result["risk"] is not None, (
        f"row {row['id']} produced no decision. The engine logged nothing for "
        f"user {result['user_id']}, so the login did not reach evaluation. "
        f"steps={result['steps']}"
    )

    # The arithmetic, against the engine's own list of what changed. Skipped where a
    # rule replaced the score rather than adjusting it, since then no band applies.
    if "tentative Risk" in why:
        stated = int(why.split("tentative Risk")[1].strip()[0])
        assert stated == expected_band(signals), (
            f"row {row['id']}: the engine reported {signals} changed, which the "
            f"weight bands put at Risk {expected_band(signals)}, but it called the "
            f"tentative level Risk {stated}. Either a weight moved or a signal is "
            f"missing from the explanation.\n  why: {why}"
        )

    # For the choreographed rows this is the assertion that matters: the sequence
    # was set up so a particular signal would fire, and the engine's own list is
    # where that is confirmed. Checked before the level, since a missing signal
    # explains a wrong level and is the more useful failure to read.
    for signal in row.get("expect_signals", []):
        assert signal in signals, (
            f"row {row['id']} ({row['note']}) was set up so {signal} would fire, but "
            f"the engine did not report it as changed. It reported: {signals or 'none'}"
            f"\n  choreography: {result.get('choreography')}\n  why: {why}"
        )

    if row.get("expect") is not None:
        assert result["risk"] == row["expect"], (
            f"row {row['id']} ({row['note']}) expected Risk {row['expect']} but got "
            f"Risk {result['risk']}.\n  why: {why}"
        )


def _classify(why: str) -> str:
    """Which rule decided this row, read from the explanation."""
    if "denylisted attribute matched" in why:
        return "deny-list"
    if "not enough history" in why:
        return "history-gate"
    if "signals changed at once" in why:
        return "hazard"
    if "is a floor" in why:
        return "hazard-floor"
    if "allowlisted" in why:
        return "allow-list"
    if "Clean login" in why:
        return "clean"
    if "familiar" in why:
        return "familiarity"
    return "weight"


def test_no_drift_from_the_recorded_baseline(matrix, pytestconfig):
    """Runs last: writes this run's artifact, then compares it to the baseline.

    This is the assertion for everything a row cannot state itself. Twelve of the
    nineteen rows have no `expect`, because their level depends on a familiarity value
    that moves with the seeded history, so without this they would keep passing while
    the engine decided something different.

    A test rather than a fixture finaliser so that failing to write, or drifting, is
    reported as a failure instead of being swallowed during teardown.
    """
    # Every row must have run, or "no drift" would mean "nothing was checked". A -k
    # filter is legitimate, and selecting this test alone is a reasonable thing to
    # try, but neither can be allowed to report a clean comparison. Skipped rather
    # than failed: a partial selection is not a defect, and if rows are missing
    # because they errored then the run is already red where it matters.
    if len(RESULTS) != len(COMPARABLE_ROWS):
        pytest.skip(
            f"only {len(RESULTS)} of {len(COMPARABLE_ROWS)} comparable rows ran, so a "
            f"baseline comparison would be misleading. Run the whole file, with no -k "
            f"filter, to compare."
        )

    payload = _write_artifact(matrix["run"].observed)
    written = ARTIFACT_DIR / "signal-matrix.json"
    assert written.is_file()
    print(f"\nwrote {written} with {len(RESULTS)} rows")

    if pytestconfig.getoption("--update-baseline"):
        recorded = base.load_baseline()
        if recorded:
            print("\nchanges being accepted into the baseline:")
            print(base.render(base.compare(recorded, payload)))
        base.write_baseline(payload)
        base.BASELINE_MD.write_text(base.render_markdown(payload))
        print(f"\nre-recorded {base.BASELINE_JSON} and {base.BASELINE_MD}")
        print("Review the diff before committing: it is the record of what changed.")
        return

    recorded = base.load_baseline()
    if recorded is None:
        pytest.fail(
            f"no baseline at {base.BASELINE_JSON}, so the rows whose level is not "
            f"hardcoded were not really checked. Record one:\n{base.UPDATE_HINT}",
            pytrace=False,
        )

    findings = base.compare(recorded, payload)
    report = base.render(findings)
    print(f"\n{report}")
    if any(f["severity"] == "fail" for f in findings):
        pytest.fail(f"the matrix drifted from its baseline.\n\n{report}", pytrace=False)

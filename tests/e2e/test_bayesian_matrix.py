"""The same matrix, scored the way the shipped default scores it.

The Y family of tests/e2e/coverage-plan.md.

`test_signal_matrix.py` pins `weight` mode, because that is the mode whose arithmetic
can be checked. But the engine's own default is `SCORING_MODE=bayesian`, so until this
file existed the mode most deployments actually run had no functional coverage at all.
That was the single largest hole in the suite.

This runs the same rows through the Bayesian scorer, in its own realm, against its own
committed baseline. A separate module rather than a parameter on the existing one, for
two reasons: the levels are not comparable between modes, so a shared baseline would
mean every row moved whenever the mode did; and weight mode should not get slower for
everyone because a second mode exists.

**What can be asserted, and what cannot.** The two scorers reach a level by different
routes, so most levels are mode-specific and are left to the baseline. What must hold
in *both* modes is the set of rules that bypass scoring entirely:

- a denylisted attribute forces the rejection level
- the history gate short-circuits before any scoring happens
- a login with nothing changed stays at the lowest level

Those are asserted directly. Everything else is recorded and compared.

**What this file found.** The Bayesian branch returns before hazard activation, the
drop-down decay and the credibility adjustment, so three mechanisms that shape a weight
-mode decision do not run at all in the deployment default. Read
`test_a_login_where_many_signals_change_is_challenged_in_both_modes` and
`test_the_mechanisms_absent_from_bayesian_scoring_are_recorded` before assuming a rule
described elsewhere in this repository applies here.
"""

import json
import os
import pathlib

import pytest

from tests.e2e import matrix_baseline as base
from tests.e2e import matrix_choreography as choreo
from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib
from tests.e2e.matrix_rows import IP_PALETTE, ROWS

MODE = "bayesian"
BASELINE_JSON, BASELINE_MD = base.paths_for(MODE)

ARTIFACT_DIR = pathlib.Path(
    os.getenv("E2E_MATRIX_ARTIFACTS", pathlib.Path(__file__).parent / "artifacts")
)

# Rows whose expected level comes from a rule that replaces the score rather than from
# the score itself. Only these can be asserted identically in both modes.
RULE_DRIVEN = {
    "B00": 1,   # nothing changed
    "D01": 4,   # denylisted address
    "D02": 4,   # denylisted country
    "G01": 3,   # history gate
    "G02": 3,   # history gate, several signals changed
    "G03": 4,   # history gate plus a denylisted address
}

# The gate short-circuits before any scorer runs, so these rows are decided by the gate
# and report it as their mode rather than reporting the realm's scorer. That is the
# behaviour Y06 is about, so it is asserted rather than worked around.
GATE_ROWS = {"G01", "G02", "G03"}

# C01 establishes its sessions by completing logins from other addresses. In weight mode
# a new address scores Risk 3, which asks for an emailed code the harness can answer. In
# bayesian mode it scores Risk 2, which asks for TOTP, and these users have no enrolled
# authenticator, so the setup cannot complete and the row cannot mean anything. Not a
# product defect: the same login is simply challenged differently. Reachable once T02
# adds TOTP enrolment to the harness.
NEEDS_TOTP_ENROLMENT = {"C01"}

# Rows built to look like an account takeover. Their exact level is scorer-specific, but
# any scorer that lets one through unchallenged has failed at the thing it is for.
MUST_BE_CHALLENGED = {"A01", "A02", "H01"}

RESULTS: list[dict] = []


@pytest.fixture(scope="session")
def bayesian_matrix(pytestconfig):
    """A realm pinned to bayesian, with one trained golden profile."""
    updating = pytestconfig.getoption("--update-baseline")

    with env.MatrixRun(mode=MODE) as run:
        resolved = run.observed.get("scoring_mode")
        if resolved != MODE:
            pytest.exit(
                f"the run realm resolved to scoring mode {resolved!r}, not {MODE!r}, "
                f"so these rows would silently measure the wrong scorer.",
                returncode=1,
            )

        recorded = base.load_baseline(BASELINE_JSON)
        if recorded and not updating:
            drift = base.fingerprint_drift(recorded, {"run": run.observed})
            if drift:
                pytest.exit(f"bayesian matrix not run: {drift}", returncode=1)

        env.verify_ip_palette(IP_PALETTE)

        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)

            target = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
            history = lib.train(lib.BASELINE_CONTEXT, username, golden_id, target=target)
            trained = lib.completed_logins(golden_id)
            if trained < target:
                pytest.fail(
                    f"golden profile reached only {trained} completed logins, below "
                    f"the {target} the history gate needs, so every row would read the "
                    f"gate rather than its own delta. Training detail: {history}"
                )

            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original


def contributions(why: str) -> dict:
    """The signals the Bayesian scorer said pushed each way.

    A different shape from weight mode, which lists only what *changed*. The Bayesian
    explanation names contributors in both directions, including signals that matched
    and therefore built trust, so this returns two lists rather than one.
    """
    out = {"raising": [], "lowering": []}
    for segment in why.split("|"):
        segment = segment.strip().rstrip(".")
        for marker, key in (
            ("Signals pushing risk up:", "raising"),
            ("Signals building trust (lowering risk):", "lowering"),
        ):
            if segment.startswith(marker):
                listed = segment[len(marker):].strip()
                items = []
                for chunk in listed.split(","):
                    for part in chunk.split(" and "):
                        part = part.strip()
                        if part:
                            items.append(part)
                out[key] = sorted(items)
    return out


def classify(why: str) -> str:
    """Which rule decided this row, read from the explanation.

    Deliberately the same field name the weight-mode baseline uses, so one comparator
    serves both and a row that switches route is reported the same way in either.
    """
    if "denylisted attribute matched" in why:
        return "deny-list"
    if "not enough history" in why:
        return "history-gate"
    if "allowlisted" in why:
        return "allow-list"
    if "Bayesian model estimated" in why:
        return "bayesian"
    return "unknown"


def stated_probability(why: str) -> int | None:
    """The percentage the model reported, for the record rather than for an assert."""
    marker = "estimated a "
    if marker not in why:
        return None
    try:
        return int(why.split(marker, 1)[1].split("%", 1)[0])
    except (ValueError, IndexError):
        return None


@pytest.mark.parametrize(
    "row",
    [pytest.param(r, id=r["id"]) for r in ROWS if not r.get("unreachable")],
)
def test_bayesian_matrix_row(bayesian_matrix, row):
    """Y01, Y02, Y05, Y06. Every row, scored by the deployment default."""
    if row["id"] in NEEDS_TOTP_ENROLMENT:
        pytest.skip(
            "this row establishes its setup by completing logins from other "
            "addresses, which bayesian scores at Risk 2 and answers with a TOTP "
            "challenge these users cannot complete. Needs T02 (TOTP enrolment)."
        )

    before = None
    if "choreograph" in row:
        name, args = row["choreograph"]
        before = choreo.BY_NAME[name](*args)

    result = lib.run_row(
        bayesian_matrix["token"],
        bayesian_matrix["golden_id"],
        row["id"],
        row["delta"],
        clone=not row.get("gate", False),
        before=before,
        **row.get("seed", {}),
    )
    bayesian_matrix["run"].track(result["user_id"])

    why = result["why"]
    contributed = contributions(why)
    RESULTS.append({
        "id": row["id"],
        "delta": result["delta"],
        "risk": result["risk"],
        "rule": classify(why),
        # Named "signals" to match the weight-mode baseline's field, so the shared
        # comparator reports a changed contribution set the same way in both modes.
        # Here it means what pushed risk *up*, which is the closest analogue to weight
        # mode's list of what changed.
        "signals": contributed["raising"],
        "probability_percent": stated_probability(why),
        "contributions": contributed,
        "mode": result["mode"],
        "step_up": result["steps"],
        "login_completed": result["login_ok"],
        "why": why,
        "note": row["note"],
    })

    assert result["risk"] is not None, (
        f"row {row['id']} produced no decision for user {result['user_id']}; the "
        f"login did not reach evaluation. steps={result['steps']}"
    )
    # Y06, asserted from the other side: a gated row must report the gate, proving the
    # gate ran *instead of* the scorer rather than before it as a formality.
    expected_mode = "history-gate" if row["id"] in GATE_ROWS else MODE
    assert result["mode"] == expected_mode, (
        f"row {row['id']} was decided in {result['mode']!r} mode, expected "
        f"{expected_mode!r}. "
        + (
            "A gated row must be decided by the gate, before any scorer."
            if row["id"] in GATE_ROWS
            else "The realm's pinned mode did not take effect, so this row proves "
                 "nothing about the scorer it was written for."
        )
    )

    if row["id"] in RULE_DRIVEN:
        expected = RULE_DRIVEN[row["id"]]
        assert result["risk"] == expected, (
            f"row {row['id']} ({row['note']}) is decided by a rule that replaces the "
            f"score, so it must give Risk {expected} in every mode, but bayesian gave "
            f"Risk {result['risk']}.\n  why: {why}"
        )


def test_a_login_where_many_signals_change_is_challenged_in_both_modes(bayesian_matrix):
    """Y04. The takeover-shaped rows must not walk through unchallenged.

    In weight mode these are held at Risk 3 by hazard activation. That mechanism does
    not run in bayesian mode at all, so this asserts the property the mechanism exists
    to guarantee rather than the mechanism itself: whatever the scorer decides, a login
    with this many signals moving is challenged.

    Measured at the time of writing, the Bayesian model reaches Risk 4 on these rows,
    which is more severe than the hazard floor, so the missing mechanism costs nothing
    here. That is a fact about the current model, not a guarantee, which is why this
    test states the floor.
    """
    scored = {r["id"]: r for r in RESULTS}
    missing = MUST_BE_CHALLENGED - set(scored)
    assert not missing, f"rows {sorted(missing)} did not run, so this proves nothing"

    for row_id in sorted(MUST_BE_CHALLENGED):
        row = scored[row_id]
        assert row["risk"] >= 3, (
            f"row {row_id} ({row['note']}) is a login where many signals moved at "
            f"once, and bayesian scored it Risk {row['risk']}, which asks for no "
            f"step-up beyond what a quiet login gets. In weight mode hazard "
            f"activation forces at least Risk 3 here; that code is unreachable in "
            f"this mode.\n  why: {row['why']}"
        )


def test_the_mechanisms_absent_from_bayesian_scoring_are_recorded(bayesian_matrix):
    """Y08. Three weight-mode mechanisms do not run here, and that is easy to miss.

    `__evaluate_risk` returns from the bayesian branch before reaching hazard
    activation, the drop-down decay, and `_adjust_for_credibility`. Credibility is not
    lost, it becomes a model feature and appears in the explanation as "device /
    network familiarity", but the other two simply do not happen.

    This asserts the absence rather than assuming it, so if a later change routes
    bayesian through those mechanisms this test fails and says so. It is not marked
    xfail because the current behaviour is not obviously wrong: the model reaches a
    more severe level than hazard would have on every row measured. It is recorded
    because a reader who knows the weight-mode rules will otherwise expect them here.
    """
    scored = {r["id"]: r for r in RESULTS}
    hazard_shaped = [scored[i] for i in sorted(MUST_BE_CHALLENGED) if i in scored]
    assert hazard_shaped, "no takeover-shaped rows ran"

    for row in hazard_shaped:
        assert "signals changed at once" not in row["why"], (
            f"row {row['id']} shows hazard activation in bayesian mode. That branch "
            f"was unreachable when this test was written, so either the code moved or "
            f"the mode did not take effect. Update this test and Y04 together."
        )
        assert "is a floor" not in row["why"], (
            f"row {row['id']} shows the hazard floor in bayesian mode, which was "
            f"unreachable when this test was written"
        )

    quiet = scored.get("B00")
    assert quiet and "Clean login" not in quiet["why"], (
        "the drop-down path ran in bayesian mode, which was unreachable when this "
        "test was written"
    )


def test_the_pinned_scoring_mode_survives_a_parameter_rewrite(bayesian_matrix):
    """Y03. Writing parameters must not silently revert the realm to another scorer.

    Worth a test because the ordering used to matter: the parameter write replaces the
    metadata that carries the scoring config, so pinning the mode first and writing
    parameters afterwards lost the pin. A realm that silently reverted to the engine
    default would produce a full matrix of plausible, wrong numbers.
    """
    realm = bayesian_matrix["run"].realm
    assert env.resolved_scoring_mode(realm) == MODE

    env._write_params(realm)

    assert env.resolved_scoring_mode(realm) == MODE, (
        "rewriting the realm's parameters reverted its scoring mode. Anything that "
        "edits parameters must re-pin the mode afterwards, and create_run_realm's "
        "ordering is load-bearing."
    )


def _write_artifact(observed: dict) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run": {
            "config_fingerprint": observed.get("config_fingerprint"),
            "realm": observed.get("realm"),
            "scoring_mode": observed.get("scoring_mode"),
            "engine_health": (observed.get("engine_health") or {}).get("status"),
        },
        "rows": RESULTS,
    }
    (ARTIFACT_DIR / "signal-matrix-bayesian.json").write_text(
        json.dumps(payload, indent=1)
    )
    return payload


def test_no_drift_from_the_recorded_bayesian_baseline(bayesian_matrix, pytestconfig):
    """Y02. The rows with no assertable level are compared to the recorded run.

    Runs last. Most Bayesian levels cannot be predicted from the row definition, so
    without this the majority of the file would only be checking that a decision
    happened at all.
    """
    comparable = [
        r for r in ROWS
        if not r.get("unreachable") and r["id"] not in NEEDS_TOTP_ENROLMENT
    ]
    if len(RESULTS) != len(comparable):
        pytest.skip(
            f"only {len(RESULTS)} of {len(comparable)} rows ran, so a baseline "
            f"comparison would be misleading. Run the whole file to compare."
        )

    payload = _write_artifact(bayesian_matrix["run"].observed)

    if pytestconfig.getoption("--update-baseline"):
        recorded = base.load_baseline(BASELINE_JSON)
        if recorded:
            print("\nchanges being accepted into the bayesian baseline:")
            print(base.render(base.compare(recorded, payload)))
        base.write_baseline(payload, BASELINE_JSON)
        BASELINE_MD.write_text(_render_markdown(payload))
        print(f"\nre-recorded {BASELINE_JSON} and {BASELINE_MD}")
        return

    recorded = base.load_baseline(BASELINE_JSON)
    if recorded is None:
        pytest.fail(
            f"no bayesian baseline at {BASELINE_JSON}, so the rows whose level is not "
            f"rule-driven were not really checked. Record one:\n{base.UPDATE_HINT}",
            pytrace=False,
        )

    findings = base.compare(recorded, payload)
    report = base.render(findings)
    print(f"\n{report}")
    if any(f["severity"] == "fail" for f in findings):
        pytest.fail(
            f"the bayesian matrix drifted from its baseline.\n\n{report}", pytrace=False
        )


def _render_markdown(payload: dict) -> str:
    lines = [
        "# Risk-signal matrix: recorded baseline (bayesian scoring)",
        "",
        "Generated by `pytest tests/e2e/test_bayesian_matrix.py --update-baseline`.",
        "Do not edit by hand.",
        "",
        "This is the engine's *default* scoring mode. Levels here are not comparable "
        "with the weight-mode baseline; the two scorers reach a level by different "
        "routes.",
        "",
        f"Config fingerprint: `{payload['run'].get('config_fingerprint')}`",
        "",
        "| Row | Delta | Risk | p(fraud) | Raising | Lowering |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        contrib = row.get("contributions") or {}
        probability = row.get("probability_percent")
        lines.append(
            f"| {row['id']} | {row['delta'] or '(baseline)'} | {row['risk']} | "
            f"{'' if probability is None else str(probability) + '%'} | "
            f"{', '.join(contrib.get('raising') or []) or 'none'} | "
            f"{', '.join(contrib.get('lowering') or []) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


# --- Y07: the two modes, side by side ------------------------------------


def test_the_two_scoring_modes_are_compared_and_their_differences_recorded():
    """Y07. A switch between modes should be an informed decision, not a surprise.

    Reads both committed baselines and writes a comparison table. It deliberately does
    not fail on a difference: the two scorers reach a level by different routes and
    disagreeing is what they do. What it does assert is that the rules which bypass
    scoring agree, because those are supposed to be mode-independent, and a difference
    there would be a defect rather than a calibration choice.

    Needs no stack: it compares two committed files.
    """
    weight = base.load_baseline(base.paths_for("weight")[0])
    bayesian = base.load_baseline(BASELINE_JSON)
    assert weight and bayesian, "both baselines must be recorded before comparing"

    w = {r["id"]: r for r in weight["rows"]}
    b = {r["id"]: r for r in bayesian["rows"]}
    shared = sorted(set(w) & set(b))

    disagreements = []
    for row_id in shared:
        if w[row_id]["risk"] != b[row_id]["risk"]:
            disagreements.append((row_id, w[row_id]["risk"], b[row_id]["risk"]))

    lines = [
        "# Weight vs bayesian, row by row",
        "",
        "Generated by `pytest tests/e2e/test_bayesian_matrix.py`. Do not edit by hand.",
        "",
        "`bayesian` is the engine's default (`SCORING_MODE`). `weight` is what the "
        "matrix pins. Neither column is the correct one; this table exists so a "
        "change of mode is an informed decision.",
        "",
        f"{len(shared) - len(disagreements)} of {len(shared)} shared rows agree.",
        "",
        "| Row | Weight | Bayesian | Same | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row_id in shared:
        wr, br = w[row_id]["risk"], b[row_id]["risk"]
        lines.append(
            f"| {row_id} | {wr} | {br} | {'yes' if wr == br else '**no**'} | "
            f"{b[row_id].get('note', '')[:70]} |"
        )
    only_weight = sorted(set(w) - set(b))
    if only_weight:
        lines += ["", f"Not run in bayesian: {', '.join(only_weight)}."]
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "mode-comparison.md").write_text("\n".join(lines) + "\n")

    for row_id, expected in RULE_DRIVEN.items():
        if row_id not in shared:
            continue
        assert w[row_id]["risk"] == b[row_id]["risk"] == expected, (
            f"row {row_id} is decided by a rule that replaces the score, so both "
            f"modes must give Risk {expected}, but weight gave {w[row_id]['risk']} "
            f"and bayesian gave {b[row_id]['risk']}. A rule that bypasses scoring "
            f"cannot depend on the scorer."
        )

    print(
        f"\n{len(disagreements)} of {len(shared)} rows differ between modes: "
        + ", ".join(f"{r} {a}->{c}" for r, a, c in disagreements)
    )

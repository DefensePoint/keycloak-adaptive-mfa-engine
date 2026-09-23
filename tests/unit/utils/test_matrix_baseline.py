"""The signal-matrix baseline comparator, tested without the stack.

Worth unit testing despite being test tooling, because its failure mode is the worst
one available: a comparator that reports "no drift" when a level has moved makes the
whole matrix suite pass forever while saying nothing. That failure is invisible in a
green run, so it has to be checked directly.

Pure functions on dicts, so these need no Keycloak, no engine and no database.
"""

import json

import pytest

from tests.e2e.matrix_baseline import (
    compare,
    fingerprint_drift,
    normalise_why,
    render,
    render_markdown,
    write_baseline,
)

WHY_WEIGHT = (
    "2 signal(s) differ from this user's norm: network / IP address and usual "
    "device/behaviour pattern. | Weighing the changed signals by their configured "
    "importance gives a tentative Risk 2."
)


def row(row_id="S01", risk=2, rule="weight", signals=None, why=WHY_WEIGHT,
        completed=True, step_up="screenRes,password", delta="xff=1.2.3.4"):
    return {
        "id": row_id, "delta": delta, "note": "a row", "risk": risk, "rule": rule,
        "signals": signals if signals is not None else ["event_cluster_label", "ip_address"],
        "why": why, "login_completed": completed, "step_up": step_up,
    }


def run(rows, fingerprint="sha256:aaaa"):
    return {
        "run": {"config_fingerprint": fingerprint, "scoring_mode": "weight"},
        "rows": rows,
    }


# --- what must fail --------------------------------------------------------


def test_a_moved_risk_level_fails():
    findings = compare(run([row(risk=2)]), run([row(risk=3)]))

    assert [f["severity"] for f in findings] == ["fail"]
    assert findings[0]["field"] == "risk"
    assert "Risk 2 -> Risk 3" in findings[0]["detail"]


def test_a_login_that_stopped_completing_fails():
    findings = compare(run([row(completed=True)]), run([row(completed=False)]))

    assert [f["severity"] for f in findings] == ["fail"]
    assert "no longer completes" in findings[0]["detail"]


def test_a_login_that_started_completing_also_fails():
    """A row expecting rejection that now succeeds is the more serious direction."""
    findings = compare(run([row(completed=False)]), run([row(completed=True)]))

    assert [f["severity"] for f in findings] == ["fail"]
    assert "now completes" in findings[0]["detail"]


def test_failures_are_reported_before_warnings():
    """The thing that breaks the build has to be at the top of the report."""
    findings = compare(
        run([row("A", risk=2), row("B", rule="weight")]),
        run([row("A", risk=3), row("B", rule="familiarity")]),
    )

    assert [f["severity"] for f in findings] == ["fail", "warn"]


# --- what must only warn --------------------------------------------------


def test_the_same_level_by_a_different_rule_only_warns():
    findings = compare(run([row(rule="weight")]), run([row(rule="familiarity")]))

    assert [f["severity"] for f in findings] == ["warn"]
    assert "Same outcome, different route" in findings[0]["detail"]


def test_a_changed_signal_set_warns_and_names_the_difference():
    findings = compare(
        run([row(signals=["ip_address"])]),
        run([row(signals=["ip_address", "country_name"])]),
    )

    assert [f["severity"] for f in findings] == ["warn"]
    assert "now also fires country_name" in findings[0]["detail"]


def test_a_signal_that_stopped_firing_is_named_too():
    findings = compare(
        run([row(signals=["ip_address", "country_name"])]),
        run([row(signals=["ip_address"])]),
    )

    assert "no longer fires country_name" in findings[0]["detail"]


def test_reworded_reasoning_only_warns():
    findings = compare(run([row(why="old wording")]), run([row(why="new wording")]))

    assert [f["severity"] for f in findings] == ["warn"]
    assert findings[0]["field"] == "why"


def test_an_added_row_warns_rather_than_shifting_the_comparison():
    findings = compare(run([row("S01")]), run([row("S01"), row("S02")]))

    assert [f["severity"] for f in findings] == ["warn"]
    assert "S02 is new" in findings[0]["detail"]


def test_a_missing_row_warns():
    findings = compare(run([row("S01"), row("S02")]), run([row("S01")]))

    assert [f["severity"] for f in findings] == ["warn"]
    assert "in the baseline but was not run" in findings[0]["detail"]


def test_rows_are_matched_by_id_not_position():
    """Reordering ROWS must not read as every row having changed."""
    findings = compare(
        run([row("S01", risk=1), row("S02", risk=2)]),
        run([row("S02", risk=2), row("S01", risk=1)]),
    )

    assert findings == []


def test_an_unchanged_run_reports_nothing():
    findings = compare(run([row(), row("S02", risk=3)]), run([row(), row("S02", risk=3)]))

    assert findings == []
    assert render(findings) == "no drift from the recorded baseline"


# --- the ordering normalisation -------------------------------------------


def test_signal_order_in_the_explanation_is_not_a_change():
    """The engine builds the list from a set, so the order varies run to run.

    Measured on the live stack: 7 of the 19 rows differ this way between two runs of
    identical code. Without this, every run reports seven changes and a real one
    hides among them.
    """
    a = normalise_why(
        "2 signal(s) differ from this user's norm: network / IP address and country "
        "name. | Weighing gives a tentative Risk 2."
    )
    b = normalise_why(
        "2 signal(s) differ from this user's norm: country name and network / IP "
        "address. | Weighing gives a tentative Risk 2."
    )

    assert a == b


def test_normalising_preserves_the_engines_phrasing():
    """Only the order moves. The wording has to survive, or a real change hides."""
    normalised = normalise_why(
        "3 signal(s) differ from this user's norm: network / IP address, country name "
        "and browser. | Weighing gives a tentative Risk 2."
    )

    assert normalised == (
        "3 signal(s) differ from this user's norm: browser, country name and network "
        "/ IP address. | Weighing gives a tentative Risk 2."
    )
    assert "Weighing gives a tentative Risk 2." in normalised


def test_a_genuinely_reworded_explanation_still_differs_after_normalising():
    a = normalise_why("2 signal(s) differ from this user's norm: browser and device. | Old.")
    b = normalise_why("2 signal(s) differ from this user's norm: browser and device. | New.")

    assert a != b


def test_an_explanation_with_no_signal_list_is_left_alone():
    """Gate and deny-list rows never list signals."""
    why = "Not enough history yet (2 of 4 events); using the cautious default Risk 3."

    assert normalise_why(why) == why


def test_a_single_signal_needs_no_conjunction():
    assert normalise_why("1 signal(s) differ from this user's norm: browser. | x.") == (
        "1 signal(s) differ from this user's norm: browser. | x."
    )


# --- the configuration guard ----------------------------------------------


def test_a_changed_fingerprint_is_reported_as_configuration_not_drift():
    message = fingerprint_drift(run([], "sha256:old"), run([], "sha256:new"))

    assert message is not None
    assert "scoring configuration changed" in message
    assert "sha256:old" in message and "sha256:new" in message
    assert "--update-baseline" in message


def test_an_unchanged_fingerprint_reports_nothing():
    assert fingerprint_drift(run([], "sha256:same"), run([], "sha256:same")) is None


# --- recording -------------------------------------------------------------


def test_the_recorded_baseline_drops_per_run_values(tmp_path):
    """Re-recording an unchanged run must produce an empty diff.

    The realm name carries a fresh uuid every run, so recording it would put a
    guaranteed change in every regeneration and bury the real ones.
    """
    payload = {
        "run": {
            "config_fingerprint": "sha256:aaaa", "scoring_mode": "weight",
            "realm": "amfa-e2e-deadbeef", "engine_health": "ok", "ip_data": "ok",
        },
        "rows": [row()],
    }
    path = tmp_path / "signal-matrix.json"
    write_baseline(payload, path)
    recorded = json.loads(path.read_text())

    assert "realm" not in recorded["run"]
    assert recorded["run"] == {
        "config_fingerprint": "sha256:aaaa", "scoring_mode": "weight",
    }
    assert compare(recorded, payload) == []


def test_recording_keeps_every_compared_field(tmp_path):
    """A field dropped from the record is a field that silently stops being checked."""
    payload = {"run": {"config_fingerprint": "x", "scoring_mode": "weight"},
               "rows": [row()]}
    path = tmp_path / "b.json"
    write_baseline(payload, path)
    recorded = json.loads(path.read_text())["rows"][0]

    for field in ("risk", "login_completed", "rule", "signals", "step_up", "why"):
        assert field in recorded, f"{field} is compared but would not be recorded"


def test_the_markdown_baseline_has_a_row_per_row():
    payload = {"run": {"config_fingerprint": "sha256:aaaa", "scoring_mode": "weight"},
               "rows": [row("S01"), row("S02", risk=3, completed=False)]}

    text = render_markdown(payload)

    assert "| S01 |" in text and "| S02 |" in text
    assert "sha256:aaaa" in text
    # Completion rendered readably, since this file is meant to be reviewed as a diff.
    assert "| yes |" in text and "| no |" in text


@pytest.mark.parametrize("field", ["risk", "login_completed"])
def test_every_fail_field_actually_fails(field):
    """Guards the FAIL_FIELDS list itself against an edit that downgrades one."""
    before = row()
    after = dict(before)
    after[field] = 99 if field == "risk" else not before[field]

    findings = compare(run([before]), run([after]))

    assert [f["severity"] for f in findings] == ["fail"], f"{field} stopped failing"

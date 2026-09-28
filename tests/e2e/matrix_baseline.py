"""Comparing a matrix run against the committed one.

A suite that passes is not the same as a suite that has not changed. Most of the
matrix cannot assert an absolute level, because the level depends on a familiarity
value that moves with the seeded history, so 12 of the 19 rows would happily keep
passing while the engine quietly decided something different. The baseline is what
closes that gap: the recorded run is the assertion for everything the row itself
cannot pin down.

**What fails and what warns.** A risk level that moved fails, because that is a
change in what a user experiences. A login that used to complete and no longer does
fails for the same reason. Everything else warns: a different rule reaching the same
level, a different set of signals, reworded reasoning. Those are worth reading and
are usually intentional, but they do not change the outcome, and making them fail
would train people to regenerate the baseline without looking.

**Order is normalised, wording is not.** The engine builds its signal list from a
set, so the order varies between two runs of identical code. Measured: 7 of the 19
rows differ that way run to run. Compared verbatim, every run would report seven
wording changes and a real change would hide among them. `normalise_why` reorders
just the listed names, reproducing exactly what the engine would have emitted had
its set iterated in sorted order. No wording is touched, so a genuine message change
still shows.

**A configuration change is not drift.** Expected levels depend on the per-signal
weights, the band boundaries, `MIN_AUTH_EVENTS` and the hazard thresholds. Change one
weight and most rows move at once. Comparing rows in that state produces a page of
failures that all say the same thing badly, so the fingerprint is checked first and a
mismatch is reported as a configuration change instead.
"""

import json
import pathlib

BASELINE_DIR = pathlib.Path(__file__).parent / "baselines"


def paths_for(mode: str = "weight") -> tuple[pathlib.Path, pathlib.Path]:
    """The committed baseline files for a scoring mode.

    Each mode gets its own pair. The levels are not comparable between them, so a
    single shared baseline would mean every mode switch rewrote every row.
    """
    suffix = "" if mode == "weight" else f"-{mode}"
    return (
        BASELINE_DIR / f"signal-matrix{suffix}.json",
        BASELINE_DIR / f"signal-matrix{suffix}.md",
    )


BASELINE_JSON, BASELINE_MD = paths_for("weight")

UPDATE_HINT = (
    "If the change is intentional, re-record the baseline and commit the diff:\n"
    "    PYTHONPATH=. python3 -m pytest tests/e2e/test_signal_matrix.py "
    "--update-baseline"
)

# A moved level, or a login that stopped completing, is a change in what a user
# experiences. Everything else is informational. `login_completed` is a failure by the
# same logic as the level: rows exist where the expected outcome is rejection (a
# denylisted address) and rows where it is completion, and either flipping is a
# regression rather than a rewording.
FAIL_FIELDS = ("risk", "login_completed")
WARN_FIELDS = ("rule", "signals", "step_up", "why")

# Per-run values, excluded from comparison: the realm name carries a fresh uuid by
# design, and the health fields describe the stack rather than the decision.
RUN_FIELDS_COMPARED = ("config_fingerprint", "scoring_mode")


def _join_like_engine(items: list[str]) -> str:
    """Join names the way the engine's explanation builder does."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def normalise_why(why: str) -> str:
    """The explanation with its signal list in a stable order.

    Only the order of the listed names changes. The wording around them is left
    exactly as the engine emitted it, so a changed message is still visible.
    """
    marker = "differ from this user's norm:"
    if marker not in why:
        return why

    head, rest = why.split(marker, 1)
    if "|" in rest:
        listed, tail = rest.split("|", 1)
        tail = " |" + tail
    else:
        listed, tail = rest, ""

    items = []
    for chunk in listed.strip().rstrip(".").split(","):
        for part in chunk.split(" and "):
            part = part.strip()
            if part:
                items.append(part)

    return f"{head}{marker} {_join_like_engine(sorted(items))}.{tail}"


def load_baseline(path: pathlib.Path = BASELINE_JSON) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def write_baseline(payload: dict, path: pathlib.Path = BASELINE_JSON) -> None:
    """Record a run as the baseline, keeping only what is compared.

    The per-run realm name is dropped rather than recorded, so re-recording an
    unchanged run produces an empty diff and a reviewer sees only real changes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    run = {k: payload["run"].get(k) for k in RUN_FIELDS_COMPARED}
    rows = [
        {k: row[k] for k in ("id", "delta", "note", *FAIL_FIELDS, *WARN_FIELDS)}
        for row in payload["rows"]
    ]
    path.write_text(json.dumps({"run": run, "rows": rows}, indent=1) + "\n")


def render_markdown(payload: dict) -> str:
    """The baseline as a table, so a change arrives as a readable diff."""
    lines = [
        "# Risk-signal matrix: recorded baseline",
        "",
        "Generated by `pytest tests/e2e/test_signal_matrix.py --update-baseline`.",
        "Do not edit by hand.",
        "",
        f"Scoring mode: `{payload['run'].get('scoring_mode')}`  ",
        f"Config fingerprint: `{payload['run'].get('config_fingerprint')}`",
        "",
        "| Row | Delta | Risk | Rule | Completed | Signals reported |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['id']} | {row['delta'] or '(baseline)'} | {row['risk']} | "
            f"{row['rule']} | {'yes' if row['login_completed'] else 'no'} | "
            f"{', '.join(row['signals']) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


def fingerprint_drift(baseline: dict, current: dict) -> str | None:
    """A message if the configuration behind the two runs is not the same."""
    was = baseline["run"].get("config_fingerprint")
    now = current["run"].get("config_fingerprint")
    if was == now:
        return None
    return (
        f"the scoring configuration changed since the baseline was recorded.\n"
        f"  baseline: {was}\n"
        f"  current:  {now}\n"
        f"The fingerprint covers the per-signal weights, the scoring mode, "
        f"WEIGHT_RISK_BANDS, MIN_AUTH_EVENTS and the HAZARD_* thresholds. Row levels "
        f"are determined by those, so comparing rows across a change would report "
        f"every affected row as its own unrelated failure.\n{UPDATE_HINT}"
    )


def compare(baseline: dict, current: dict) -> list[dict]:
    """Differences between two runs, each tagged fail or warn.

    Rows are matched by id, so reordering `ROWS` is not a change and adding one is
    reported rather than silently shifting every comparison by one.
    """
    was = {row["id"]: row for row in baseline["rows"]}
    now = {row["id"]: row for row in current["rows"]}
    findings = []

    for row_id in sorted(set(was) - set(now)):
        findings.append({
            "severity": "warn", "row": row_id, "field": "row",
            "detail": (
                f"row {row_id} is in the baseline but was not run. Deleted "
                f"deliberately, or deselected by a -k filter?"
            ),
        })
    for row_id in sorted(set(now) - set(was)):
        findings.append({
            "severity": "warn", "row": row_id, "field": "row",
            "detail": f"row {row_id} is new and has no recorded baseline yet.",
        })

    for row_id in sorted(set(was) & set(now)):
        for field in FAIL_FIELDS + WARN_FIELDS:
            before, after = was[row_id].get(field), now[row_id].get(field)
            if before == after:
                continue
            severity = "fail" if field in FAIL_FIELDS else "warn"
            findings.append({
                "severity": severity, "row": row_id, "field": field,
                "baseline": before, "current": after,
                "detail": _describe(row_id, field, before, after, now[row_id]),
            })

    # Failures first, so the thing that breaks the build is at the top of the report.
    findings.sort(key=lambda f: (f["severity"] != "fail", f["row"], f["field"]))
    return findings


def _describe(row_id: str, field: str, before, after, row: dict) -> str:
    if field == "risk":
        return (
            f"{row_id}: Risk {before} -> Risk {after}. {row.get('note', '')}\n"
            f"      now: {row.get('why', '')}"
        )
    if field == "login_completed":
        moved = "no longer completes" if before else "now completes"
        return f"{row_id}: the login {moved} (was {before}, now {after})."
    if field == "signals":
        gained = sorted(set(after or []) - set(before or []))
        lost = sorted(set(before or []) - set(after or []))
        parts = []
        if gained:
            parts.append(f"now also fires {', '.join(gained)}")
        if lost:
            parts.append(f"no longer fires {', '.join(lost)}")
        return f"{row_id}: {'; '.join(parts)} (level unchanged at Risk {row['risk']})."
    if field == "rule":
        return (
            f"{row_id}: reached Risk {row['risk']} via '{after}' where the baseline "
            f"used '{before}'. Same outcome, different route."
        )
    if field == "why":
        return f"{row_id}: reasoning reworded.\n      was: {before}\n      now: {after}"
    return f"{row_id}: {field} {before!r} -> {after!r}"


def render(findings: list[dict]) -> str:
    if not findings:
        return "no drift from the recorded baseline"
    fails = [f for f in findings if f["severity"] == "fail"]
    warns = [f for f in findings if f["severity"] == "warn"]

    lines = []
    if fails:
        lines.append(f"{len(fails)} change(s) to what a user experiences:")
        lines += [f"  FAIL  {f['detail']}" for f in fails]
    if warns:
        if fails:
            lines.append("")
        lines.append(f"{len(warns)} change(s) that did not move any level:")
        lines += [f"  warn  {f['detail']}" for f in warns]
    if fails:
        lines += ["", UPDATE_HINT]
    return "\n".join(lines)

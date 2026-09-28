"""Per-realm parameters: what they change, and what they must not.

The P and M families of tests/e2e/coverage-plan.md.

The matrix runs against one parameter set, so it proves the engine scores correctly
under that configuration. It cannot show that the configuration is what produced the
answer. These tests build realms that differ from it in one stated way each, and check
that the difference lands.

That matters more than it sounds. Per-realm parameters are the product: a deployment
tunes weights, switches signals off, and maintains allow and deny lists per realm. If a
parameter were ignored, every matrix row would still pass, because the matrix never
varies one.

**Isolation, and what it unlocks.** `event_cluster_label` clusters the whole context
vector, so it fires on essentially any change and no single-signal delta is really
single. That is why the matrix asserts weight arithmetic in aggregate rather than
per signal. A realm with that one parameter switched off makes true isolation possible,
and with it the band boundaries: see the M family at the bottom of this file, which is
the first direct check that a weight of 2 is worth 2.
"""

import pytest

from tests.e2e import matrix_env as env
from tests.e2e import matrix_lib as lib

# A second address on both lists at once, so precedence can be observed rather than
# argued about. Non-public on purpose: it resolves to no country, so the only thing
# the row changes is membership of the two lists.
CONTESTED_IP = "203.0.113.11"


def run_in(realm_run, row_id: str, delta: dict, **kwargs) -> dict:
    """One row against an already-configured realm."""
    original = lib.REALM
    lib.REALM = realm_run["run"].realm
    try:
        result = lib.run_row(
            realm_run["token"], realm_run["golden_id"], row_id, delta, **kwargs
        )
        realm_run["run"].track(result["user_id"])
        return result
    finally:
        lib.REALM = original


def trained_realm(overrides: dict | None = None, write_params: bool = True):
    """A realm with the given parameter overrides and one trained golden profile.

    Written as a plain generator so each fixture below can declare its own overrides
    without repeating twenty lines of setup.
    """
    with env.MatrixRun(overrides=overrides, write_params=write_params) as run:
        original = lib.REALM
        lib.REALM = run.realm
        try:
            token = lib.admin_token()
            username, golden_id = lib.create_user(token, "golden")
            run.track(golden_id)
            target = int(env._engine_scoring_env()["MIN_AUTH_EVENTS"])
            lib.train(lib.BASELINE_CONTEXT, username, golden_id, target=target)
            trained = lib.completed_logins(golden_id)
            if trained < target:
                pytest.fail(
                    f"golden profile reached only {trained} of the {target} logins the "
                    f"history gate needs, so every row would read the gate"
                )
            yield {"run": run, "token": token, "golden_id": golden_id}
        finally:
            lib.REALM = original


@pytest.fixture(scope="module")
def isolated_realm():
    """`event_cluster_label` off, so one changed field is one changed signal."""
    yield from trained_realm({"disabled": {"event_cluster_label"}})


@pytest.fixture(scope="module")
def geo_realm():
    """`geo_loc` on, the one signal the matrix parameter set switches off."""
    yield from trained_realm({"enabled": {"geo_loc"}})


# --- P02: a disabled signal contributes nothing ---------------------------


def test_a_disabled_signal_does_not_fire_even_when_its_condition_is_met(
    isolated_realm,
):
    """P02. Switching a signal off must stop it scoring, not just stop it being listed.

    Driven with a delta that certainly changes the cluster, in a realm where the
    cluster signal is disabled. The container-side test proves the parameter reaches
    the engine; this proves it changes a real decision.
    """
    result = run_in(
        isolated_realm, "P02", {"user_agent": lib.BASELINE_CONTEXT["user_agent"]
                                .replace("Chrome/150", "Chrome/151")}
    )

    assert "usual device/behaviour pattern" not in result["why"], (
        f"event_cluster_label is disabled in this realm but still appears in the "
        f"engine's explanation.\n  why: {result['why']}"
    )


# --- P01 and M: isolation makes per-signal weights checkable --------------

# Deltas that move exactly one signal once the cluster is out of the way, with the
# weight that signal carries in the matrix parameter set.
SINGLE_SIGNAL_DELTAS = [
    pytest.param({"user_agent": lib.BASELINE_CONTEXT["user_agent"].replace(
        "Chrome/150.0.0.0", "Firefox/130.0")}, "browser", 1, id="browser-weight-1"),
    pytest.param({"screen_res": "1024x768"}, "screen size", 1, id="screen-weight-1"),
    pytest.param({"accept_language": "fr-FR,fr;q=0.9"}, "browser language", 2,
                 id="language-weight-2"),
]


@pytest.mark.parametrize("delta,label,weight", SINGLE_SIGNAL_DELTAS)
def test_one_changed_field_is_one_changed_signal_when_the_cluster_is_off(
    isolated_realm, delta, label, weight
):
    """P01. The isolation this unlocks, checked before anything is built on it.

    The matrix cannot do this: with `event_cluster_label` enabled, changing the
    browser reports two changed signals, so a per-signal weight is never observable.
    Here exactly one signal should be named.
    """
    result = run_in(isolated_realm, f"P01-{label[:6]}", delta)

    why = result["why"]
    assert "differ from this user's norm" in why, (
        f"changing {label} produced no reported change at all.\n  why: {why}"
    )
    listed = why.split("differ from this user's norm:", 1)[1].split("|")[0]
    assert label in listed, f"expected {label!r} among the changed signals: {listed}"
    assert listed.count(",") == 0 and " and " not in listed, (
        f"changing {label} reported more than one changed signal, so this realm is "
        f"not isolating as intended: {listed.strip()}"
    )


@pytest.mark.parametrize(
    "delta,expected_band,description",
    [
        pytest.param({"user_agent": lib.BASELINE_CONTEXT["user_agent"].replace(
            "Chrome/150.0.0.0", "Firefox/130.0")}, 1,
            "browser alone, weight 1, below the first band", id="sum-1-gives-risk-1"),
        pytest.param({"accept_language": "fr-FR,fr;q=0.9"}, 1,
            "language alone, weight 2, still below the first band",
            id="sum-2-gives-risk-1"),
    ],
)
def test_a_weight_sum_lands_in_the_documented_band(
    isolated_realm, delta, expected_band, description
):
    """M01. A weight below the first boundary gives the lowest level.

    The bands are (3, 6): under 3 is Risk 1, 3 to 5 is Risk 2, 6 or more is Risk 3.
    With the cluster disabled these sums are finally reachable one signal at a time.

    Only the sums reachable with a single signal are asserted here. Combinations that
    would land exactly on 3 or 6 also move the familiarity value, which adjusts the
    level afterwards, so they are not a clean read of the band and are left to the
    matrix's aggregate arithmetic check.
    """
    result = run_in(isolated_realm, "M01", delta)

    tentative = result["why"].split("tentative Risk")
    assert len(tentative) > 1, (
        f"no weighted score was reported for {description}, so the band cannot be "
        f"read.\n  why: {result['why']}"
    )
    stated = int(tentative[1].strip()[0])
    assert stated == expected_band, (
        f"{description} produced a tentative Risk {stated}, expected "
        f"{expected_band}.\n  why: {result['why']}"
    )


# --- X02: the signal the matrix switches off ------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "geo_loc is a dead parameter: it can be configured and weighted, and nothing "
        "ever evaluates it. It ships in DEFAULT_DECISION_PARAMS with weight 3 and "
        "disabled True, so it is offered as a tunable signal, but eval_risk.py "
        "computes each signal behind an explicit `if \"<name>\" in enabled_params` "
        "block and there is no such block for geo_loc. Grepping the engine finds the "
        "name in exactly one place, its own default entry. Enabling it therefore does "
        "nothing at all, silently: an operator who switches it on and gives it a "
        "weight gets no effect and no warning, and may reasonably believe location is "
        "being scored when the work is actually done by geolocation_cluster_label and "
        "country_name. The fix is a decision, either implement the signal or drop the "
        "parameter, and if it is dropped this test should be deleted rather than "
        "unmarked."
    ),
)
def test_enabling_geo_loc_makes_a_moved_location_contribute(geo_realm):
    """X02. `geo_loc` is disabled in the matrix, so nothing covers it anywhere.

    Enabled here and driven with an address in another country, which moves the
    coordinates the signal would be computed from.
    """
    result = run_in(geo_realm, "X02", {"xff": "193.99.144.80"})

    assert result["risk"] is not None, "the login produced no decision"
    assert "geo_loc" in result["why"] or "coordinates" in result["why"].lower(), (
        f"with geo_loc enabled, a login from another country reported no signal from "
        f"it. Note geolocation_cluster_label is a different parameter and does fire "
        f"here, which is what makes the dead one easy to miss.\n"
        f"  why: {result['why']}"
    )


# --- P03: a realm nobody configured ---------------------------------------


def test_a_realm_with_no_parameters_of_its_own_scores_nothing(request):
    """P03. The shipped defaults disable every signal, which is easy to not know.

    A realm that has never had parameters written falls back to `default`/`default`,
    and `DEFAULT_DECISION_PARAMS` ships with all nineteen signals disabled. So an
    unconfigured realm does not score cautiously, it does not score at all. Worth a
    test because the failure mode is silent: every login looks fine.
    """
    runs = trained_realm(write_params=False)
    realm_run = next(runs)
    try:
        result = run_in(
            realm_run, "P03", {"user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
                               "xff": "193.99.144.80"}
        )

        assert "differ from this user's norm" not in result["why"], (
            f"an unconfigured realm reported changed signals, so it is scoring "
            f"against some parameter set. If the shipped defaults changed, this test "
            f"and the plan's note about them need updating.\n  why: {result['why']}"
        )
    finally:
        for _ in runs:
            pass


# --- P05: precedence between the two hard overrides -----------------------


@pytest.fixture(scope="module")
def contested_realm():
    """One address on the allow list and the deny list at the same time."""
    yield from trained_realm({
        "lists": {
            "ip_address": {
                "blacklist": ["203.0.113.9", CONTESTED_IP],
                "whitelist": ["203.0.113.7", CONTESTED_IP],
            }
        }
    })


def test_a_denylisted_address_beats_an_allowlisted_one(contested_realm):
    """P05. When both hard overrides match, the restrictive one must win.

    Not a hypothetical conflict: allow and deny lists are edited by different people
    at different times, and an address can end up on both. If the allow list won, a
    stale allow entry would silently neutralise a deliberate block.

    The engine resolves this deliberately rather than by accident, and not the way a
    plain "deny wins" rule would: the denylist wins, but the level is tempered to a
    Risk 3 floor instead of the Risk 4 an uncontested denylist forces. So an allow
    entry does soften a block, it just cannot cancel it. Asserted as the documented
    behaviour, with the tempering named, because a future change in either direction
    should have to edit this test and say why.
    """
    uncontested = run_in(contested_realm, "P05-deny", {"xff": "203.0.113.9"})
    contested = run_in(contested_realm, "P05", {"xff": CONTESTED_IP})

    assert uncontested["risk"] == 4, (
        f"an address on the denylist alone gave Risk {uncontested['risk']}, so this "
        f"realm's lists are not what the test thinks.\n  why: {uncontested['why']}"
    )
    assert contested["risk"] == 3, (
        f"an address on both lists produced Risk {contested['risk']}. The documented "
        f"resolution is the denylist winning, tempered to a Risk 3 floor.\n"
        f"  why: {contested['why']}"
    )
    assert "denylist wins" in contested["why"], (
        f"the conflict was resolved without saying so. An operator reading the log "
        f"has to be able to see that both lists matched.\n  why: {contested['why']}"
    )
    assert contested["risk"] < uncontested["risk"], (
        "an allowlist entry made no difference at all to a denylisted address; if "
        "that is now intended, this test and the engine's explanation disagree"
    )


# --- P06: a per-realm threshold -------------------------------------------


@pytest.fixture(scope="module")
def short_dormancy_realm():
    """Dormancy after 5 days instead of the default 40."""
    yield from trained_realm({"inactive_days": 5})


def test_the_dormancy_threshold_is_honoured_per_realm(short_dormancy_realm):
    """P06. A threshold in the realm's parameters must change a real decision.

    The container-side test proves the value round-trips through the settings API.
    This proves the engine scores by it: history that is not dormant under the default
    40 days is dormant under this realm's 5.
    """
    dormant = run_in(short_dormancy_realm, "P06", {}, days_ago_of_oldest=14)

    assert "long-dormant account" in dormant["why"], (
        f"history ending 10 days ago was not called dormant in a realm whose "
        f"threshold is 5 days, so the per-realm value was not used.\n"
        f"  why: {dormant['why']}"
    )


def test_recent_history_is_not_dormant_under_the_same_threshold(short_dormancy_realm):
    """P06, the other side. A threshold that fires for everything proves nothing."""
    recent = run_in(short_dormancy_realm, "P06b", {}, days_ago_of_oldest=8)

    assert "long-dormant account" not in recent["why"], (
        f"history ending 4 days ago was called dormant under a 5-day threshold.\n"
        f"  why: {recent['why']}"
    )

"""How device and network familiarity move a decision.

c = 0.55 * device + 0.45 * network. A familiar device alone reaches 0.64 even on a
network the user has never used, so the network half is judged on its own as well:
a known device does not vouch for a new address, country or anonymiser. Nor does
a familiar login vouch for the account: a concurrent session, impossible travel or
a recent credential change is never lowered by familiarity.
"""

import pytest

from src.service.decision import ACCOUNT_SIGNALS, DecisionService


def service() -> DecisionService:
    """Only the state the adjustment reads; see test_hazard_floor.py."""
    svc = DecisionService.__new__(DecisionService)
    svc.explain = []
    svc.risk_floor = 0
    return svc


def adjust(svc, device, network, decision, whitelisted=None):
    c = device * 0.55 + network * 0.45
    return svc._adjust_for_credibility(
        c=c, decision=decision, whitelisted_vars=whitelisted, network_credibility=network
    )


def test_a_known_device_on_a_new_network_is_raised_like_an_unfamiliar_one():
    svc = service()
    assert adjust(svc, 1.0, 0.2, 2) == 3
    assert "network is new to the user" in " ".join(svc.explain)


def test_a_known_device_on_a_new_network_is_never_lowered():
    assert adjust(service(), 1.0, 0.2, 3) == 3


def test_an_allowlisted_new_network_is_not_raised_and_says_why():
    svc = service()
    assert adjust(svc, 1.0, 0.2, 2, whitelisted=[{"ip_address": "203.0.113.7"}]) == 2
    assert "allowlisted" in " ".join(svc.explain)


def test_a_partly_familiar_network_leaves_the_score_alone():
    assert adjust(service(), 1.0, 0.5, 3) == 3


def test_an_unused_device_on_a_familiar_network_leaves_the_score_alone():
    assert adjust(service(), 0.2, 1.0, 2) == 2


def test_both_familiar_lower_by_one_step():
    assert adjust(service(), 1.0, 1.0, 3) == 2
    assert adjust(service(), 1.0, 0.7, 2) == 1


def test_both_unfamiliar_raise_to_three():
    assert adjust(service(), 0.2, 0.2, 1) == 3


def test_without_the_network_half_the_combined_value_decides():
    svc = service()
    assert svc._adjust_for_credibility(c=0.7, decision=3) == 2
    assert svc._adjust_for_credibility(c=0.1, decision=1) == 3


def test_a_clean_login_already_relaxed_by_the_drop_down_is_not_lowered_again():
    svc = service()
    assert svc._adjust_for_credibility(
        c=1.0, decision=2, network_credibility=1.0, allow_lowering=False
    ) == 2


def test_a_clean_login_on_a_new_network_is_still_raised():
    svc = service()
    assert svc._adjust_for_credibility(
        c=0.64, decision=1, network_credibility=0.2, allow_lowering=False
    ) == 3



def test_a_login_with_changed_signals_may_be_lowered():
    assert service()._familiarity_may_lower(["ip_address", "time_of_day"], []) is True


def test_a_denylisted_login_may_be_lowered_like_any_scored_one():
    assert service()._familiarity_may_lower([], ["ip_address"]) is True


def test_a_clean_login_may_not_be_lowered():
    assert service()._familiarity_may_lower([], []) is False


@pytest.mark.parametrize("signal", sorted(ACCOUNT_SIGNALS))
def test_an_account_signal_is_never_lowered_and_says_why(signal):
    svc = service()
    assert svc._familiarity_may_lower(["ip_address", signal], []) is False
    why = " ".join(svc.explain)
    assert "Familiarity does not lower this level" in why
    assert "concerns the account" in why


def test_two_account_signals_are_named_together():
    svc = service()
    assert svc._familiarity_may_lower(["concurrent_session", "impossible_travel"], []) is False
    assert "concern the account" in " ".join(svc.explain)


def test_the_account_signals_are_the_three_that_describe_the_account():
    assert ACCOUNT_SIGNALS == {"concurrent_session", "impossible_travel", "recent_account_change"}

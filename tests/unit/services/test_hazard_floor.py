"""A hazard escalation is a floor the familiarity adjustment cannot lower.

Hazard activation escalates when many signals change at once, which is the shape of
an account takeover: the device stays familiar while the network, country, language
and hour all move. The device/network familiarity adjustment runs afterwards, so
before this it could subtract from the very escalation written for that case, and the
engine would state both things about one login:

    6 signals changed at once, which is a very unfamiliar context; forcing Risk 3
    This device/network is fairly familiar (0.64, high); lowering from Risk 3 to Risk 2

The floor removes the contradiction in the direction that matters. Familiarity still
lowers an ordinary weight-based score, which is what keeps a known device from being
challenged constantly.
"""

import pytest

from src.service.decision import DecisionService


def service_with_floor(floor: int) -> DecisionService:
    """A service instance with only the state the adjustment reads.

    Built without __init__ deliberately: the adjustment is a pure function of the
    credibility value, the incoming decision and the floor, and constructing the real
    thing would require Redis and a request payload for no added coverage.
    """
    service = DecisionService.__new__(DecisionService)
    service.explain = []
    service.risk_floor = floor
    return service


def adjust(service: DecisionService, credibility: float, decision: int) -> int:
    """Run the credibility adjustment the way __evaluate_risk does."""
    return service._adjust_for_credibility(c=credibility, decision=decision)


# --- the floor holds -------------------------------------------------------


def test_high_familiarity_cannot_lower_a_hazard_forced_three():
    service = service_with_floor(3)

    assert adjust(service, 0.7, 3) == 3
    assert any("is a floor" in step for step in service.explain)


def test_very_high_familiarity_cannot_collapse_a_hazard_forced_three():
    """The dangerous case: this branch used to set the level to 1 outright."""
    service = service_with_floor(3)

    assert adjust(service, 0.95, 3) == 3
    assert any("is a floor" in step for step in service.explain)


def test_very_high_familiarity_cannot_collapse_a_hazard_forced_four():
    service = service_with_floor(4)

    assert adjust(service, 0.99, 4) == 4


def test_the_block_is_explained_not_silent():
    """An operator reading the log must see why the usual lowering did not happen."""
    service = service_with_floor(3)
    adjust(service, 0.95, 3)

    joined = " ".join(service.explain)
    assert "very familiar" in joined
    assert "floor" in joined
    assert "staying at Risk 3" in joined


# --- ordinary scores are still lowered ------------------------------------


def test_without_a_floor_high_familiarity_still_lowers_by_one():
    service = service_with_floor(0)

    assert adjust(service, 0.7, 3) == 2


def test_without_a_floor_very_high_familiarity_still_collapses_to_one():
    service = service_with_floor(0)

    assert adjust(service, 0.95, 3) == 1


def test_a_floor_below_the_result_does_not_interfere():
    """A floor only blocks a lowering that would breach it."""
    service = service_with_floor(2)

    # 3 -> 2 does not go below the floor, so it proceeds.
    assert adjust(service, 0.7, 3) == 2


def test_risk_one_is_untouched_whatever_the_familiarity():
    service = service_with_floor(0)

    assert adjust(service, 0.99, 1) == 1


# --- raising is unaffected ------------------------------------------------


def test_low_familiarity_still_raises_to_three():
    """The floor is about lowering; the unfamiliar-context branch is unchanged."""
    service = service_with_floor(0)
    service.explain = []

    assert adjust(service, 0.1, 1) == 3


def test_missing_attribute_is_treated_as_no_floor():
    """Unit tests elsewhere build this class without __init__.

    The adjustment must not require the attribute to exist, or those tests break on
    an AttributeError that has nothing to do with what they are checking.
    """
    service = DecisionService.__new__(DecisionService)
    service.explain = []

    assert adjust(service, 0.95, 3) == 1

"""The provider contract.

Every provider, on every code path, must return exactly the contract keys. This
is the test that catches drift: a provider that quietly omits a key makes the
shim fall back to a default, and a "not checked" result then reads as "checked
and clean" at the point where it changes an authentication decision.
"""

import pytest

from src.utils.info_provider.ip_intel.base import (
    ALL_LABELS,
    ANONYMITY_RESULT_KEYS,
    ANONYMITY_UNRESOLVED,
    DETECTION_LABELS,
    GEO_RESULT_KEYS,
    GEO_UNRESOLVED,
    HIGH_CONFIDENCE_LABELS,
    MEDIUM_CONFIDENCE_LABELS,
    SUPPRESSION_LABELS,
    anonymity_unresolved,
    geo_unresolved,
)


def test_unresolved_factories_match_the_contract_exactly():
    assert set(geo_unresolved("x")) == GEO_RESULT_KEYS
    assert set(anonymity_unresolved("x")) == ANONYMITY_RESULT_KEYS


def test_unresolved_factories_mark_the_result_unresolved():
    assert geo_unresolved("x")["resolved"] is False
    assert anonymity_unresolved("x")["resolved"] is False
    assert anonymity_unresolved("x")["is_vpn"] is False


def test_the_source_is_recorded():
    assert geo_unresolved("bundled-db")["source"] == "bundled-db"
    assert anonymity_unresolved("bundle-unavailable")["source"] == (
        "bundle-unavailable"
    )


def test_unresolved_anonymity_defaults_to_everything_unchecked():
    """Nothing was consulted, so no label may be reported as evaluated."""
    assert set(anonymity_unresolved("x")["unchecked"]) == set(ALL_LABELS)


def test_unchecked_can_be_narrowed_by_the_caller():
    result = anonymity_unresolved("x", unchecked=["tor_exit"])

    assert result["unchecked"] == ["tor_exit"]


def test_factories_do_not_share_mutable_state():
    """The shared templates must never be handed out by reference.

    A caller mutating one result would otherwise corrupt the default for every
    later lookup in the process.
    """
    first = anonymity_unresolved("a")
    first["labels"].append("tor_exit")
    first["unchecked"].append("bogus")

    second = anonymity_unresolved("b")

    assert second["labels"] == []
    assert "bogus" not in second["unchecked"]
    assert ANONYMITY_UNRESOLVED["labels"] == []

    geo_first = geo_unresolved("a")
    geo_first["country_iso"] = "ZZ"
    assert geo_unresolved("b")["country_iso"] != "ZZ"
    assert GEO_UNRESOLVED["resolved"] is False


# -- label taxonomy --------------------------------------------------------


def test_label_groups_are_disjoint():
    """A label that both suppresses and detects would make the override ambiguous."""
    assert not set(SUPPRESSION_LABELS) & set(DETECTION_LABELS)
    assert not set(HIGH_CONFIDENCE_LABELS) & set(MEDIUM_CONFIDENCE_LABELS)


def test_every_detection_label_has_a_confidence_tier():
    assert set(DETECTION_LABELS) == set(HIGH_CONFIDENCE_LABELS) | set(
        MEDIUM_CONFIDENCE_LABELS
    )


def test_all_labels_is_the_union():
    assert set(ALL_LABELS) == set(SUPPRESSION_LABELS) | set(DETECTION_LABELS)
    assert len(ALL_LABELS) == len(set(ALL_LABELS))  # no duplicates


def test_datacenter_is_only_medium_confidence():
    """Hosting membership is weaker evidence than a Tor or VPN listing.

    Legitimate cloud egress, CDNs and corporate NAT all live in hosting ranges,
    so this label alone cannot carry a positive verdict.
    """
    assert "datacenter" in MEDIUM_CONFIDENCE_LABELS
    assert "datacenter" not in HIGH_CONFIDENCE_LABELS

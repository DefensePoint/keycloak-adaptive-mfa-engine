"""Bundled anonymiser classification.

The behaviours protected here are the ones that decide whether a real user gets
challenged: suppression beating detection, "unchecked" never reading as clean,
and a missing bundle degrading instead of raising.
"""

import json
import time
from pathlib import Path

import pytest

from src.utils.info_provider.ip_intel import local_anon
from src.utils.info_provider.ip_intel.base import (
    ANONYMITY_RESULT_KEYS,
    ALL_LABELS,
)
from src.utils.info_provider.ip_intel.local_anon import AnonymiserIndex

TOR = "77.77.77.77"
VPN = "88.88.88.88"
DC = "45.45.45.45"
CLEAN = "8.8.4.4"


def build_bundle(tmp_path, lists=None, hosting_asns=None, build_epoch=None):
    """Write a bundle directory and return its path.

    The default build date is *now*, so tests exercise the fresh-data path. A
    fixed past epoch would silently drift over the staleness threshold and start
    penalising confidence, which is a property with its own test below.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    if build_epoch is None:
        build_epoch = int(time.time())
    manifest = {"build_epoch": build_epoch, "lists": {}}

    for label, entries in (lists or {}).items():
        filename = f"{label}.txt"
        (tmp_path / filename).write_text("\n".join(entries), encoding="utf-8")
        manifest["lists"][label] = filename

    if hosting_asns is not None:
        (tmp_path / "asns.txt").write_text("\n".join(hosting_asns), encoding="utf-8")
        manifest["hosting_asns"] = "asns.txt"

    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def no_asn_lookup(monkeypatch):
    """Isolate list behaviour from the ASN database, which tests supply directly."""
    monkeypatch.setattr(local_anon, "lookup_asn", lambda ip: (None, None))


@pytest.fixture
def full_bundle(tmp_path, no_asn_lookup):
    return AnonymiserIndex(
        build_bundle(
            tmp_path,
            lists={
                "tor_exit": ["77.77.77.0/24"],
                "commercial_vpn": ["88.88.88.0/24"],
                "datacenter": ["45.45.45.0/24"],
                "privacy_relay": ["45.45.45.128/25"],
                "corporate_egress": ["88.88.88.128/25"],
            },
        )
    )


# -- the contract ----------------------------------------------------------


@pytest.mark.parametrize("ip", [TOR, DC, CLEAN, "10.0.0.1", "not-an-ip"])
def test_every_path_returns_the_full_contract(full_bundle, ip):
    result = full_bundle.classify(ip)

    assert set(result) == ANONYMITY_RESULT_KEYS
    assert isinstance(result["labels"], list)
    assert isinstance(result["is_vpn"], bool)
    assert isinstance(result["unchecked"], list)


# -- detection -------------------------------------------------------------


def test_tor_exit_is_flagged_with_high_confidence(full_bundle):
    result = full_bundle.classify(TOR)

    assert result["labels"] == ["tor_exit"]
    assert result["is_vpn"] is True
    assert result["confidence"] >= 90
    assert result["resolved"] is True
    assert result["unchecked"] == []


def test_commercial_vpn_is_flagged(full_bundle):
    result = full_bundle.classify(VPN)

    assert "commercial_vpn" in result["labels"]
    assert result["is_vpn"] is True


def test_clean_address_is_not_flagged(full_bundle):
    result = full_bundle.classify(CLEAN)

    assert result["labels"] == []
    assert result["is_vpn"] is False
    assert result["resolved"] is True
    # Full coverage, so a clean verdict is stated at full strength.
    assert result["confidence"] == 90


# -- the datacenter flag ---------------------------------------------------


def test_datacenter_alone_does_not_mean_vpn_by_default(full_bundle, monkeypatch):
    """Hosting membership is reported as evidence but is not itself a verdict.

    Cloud egress, CDNs and corporate NAT all live in hosting ranges, so treating
    the label as a VPN is what produces false challenges for ordinary users.
    """
    monkeypatch.setattr(local_anon, "ANON_DATACENTER_IS_VPN", False)

    result = full_bundle.classify(DC)

    assert result["labels"] == ["datacenter"]
    assert result["is_vpn"] is False
    # The evidence is still reported, at medium strength.
    assert result["confidence"] < 90


def test_datacenter_means_vpn_when_the_operator_opts_in(full_bundle, monkeypatch):
    monkeypatch.setattr(local_anon, "ANON_DATACENTER_IS_VPN", True)

    result = full_bundle.classify(DC)

    assert result["labels"] == ["datacenter"]
    assert result["is_vpn"] is True


def test_hosting_asn_adds_the_datacenter_label(tmp_path, monkeypatch):
    """The ASN join catches hosting ranges the CIDR lists miss."""
    monkeypatch.setattr(local_anon, "lookup_asn", lambda ip: (15169, "Example"))
    index = AnonymiserIndex(
        build_bundle(
            tmp_path,
            lists={"datacenter": ["45.45.45.0/24"]},
            hosting_asns=["AS15169\tExample\tUS"],
        )
    )

    # Outside every datacenter CIDR, but inside a hosting ASN.
    result = index.classify("1.2.3.4")

    assert result["labels"] == ["datacenter"]


def test_asn_label_is_not_duplicated_when_the_cidr_also_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(local_anon, "lookup_asn", lambda ip: (15169, "Example"))
    index = AnonymiserIndex(
        build_bundle(
            tmp_path,
            lists={"datacenter": ["45.45.45.0/24"]},
            hosting_asns=["15169"],
        )
    )

    assert index.classify(DC)["labels"] == ["datacenter"]


# -- suppression -----------------------------------------------------------


def test_suppression_overrides_a_datacenter_match(full_bundle, monkeypatch):
    """Apple Private Relay sits inside hosting ranges and must not read as a VPN."""
    monkeypatch.setattr(local_anon, "ANON_DATACENTER_IS_VPN", True)

    result = full_bundle.classify("45.45.45.200")  # in datacenter AND privacy_relay

    assert set(result["labels"]) == {"datacenter", "privacy_relay"}
    assert result["is_vpn"] is False


def test_suppression_overrides_even_a_high_confidence_match(full_bundle):
    """Corporate egress wins over a commercial-VPN listing.

    An enterprise SASE range that a VPN feed also lists is the operator's own
    egress, and challenging every employee behind it is the worse error.
    """
    result = full_bundle.classify("88.88.88.200")  # commercial_vpn AND corporate_egress

    assert set(result["labels"]) == {"commercial_vpn", "corporate_egress"}
    assert result["is_vpn"] is False


# -- coverage honesty ------------------------------------------------------


def test_ipv6_reports_ipv4_only_lists_as_unchecked(tmp_path, monkeypatch):
    """The central honesty property: unchecked is not clean.

    The bundled Tor and VPN lists are IPv4-only. For an IPv6 client only the
    ASN-backed datacenter check can answer, and the result must say so rather
    than implying we looked for Tor.
    """
    monkeypatch.setattr(local_anon, "lookup_asn", lambda ip: (13335, "Example"))
    index = AnonymiserIndex(
        build_bundle(
            tmp_path,
            lists={"tor_exit": ["77.77.77.0/24"]},  # v4 only
            hosting_asns=["13335"],
        )
    )

    result = index.classify("2606:4700:4700::1111")

    assert "tor_exit" in result["unchecked"]
    assert "datacenter" not in result["unchecked"]  # the ASN check did answer
    assert result["resolved"] is True
    assert result["confidence"] < 90  # weaker, because detection coverage is partial
    assert result["source"].endswith("-partial")


def test_ipv6_with_no_ipv6_capable_source_is_unresolved(tmp_path, no_asn_lookup):
    """No detection source could answer, so we report nothing rather than clean."""
    index = AnonymiserIndex(
        build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    )

    result = index.classify("2606:4700:4700::1111")

    assert result["resolved"] is False
    assert result["is_vpn"] is False
    assert set(result["unchecked"]) == set(ALL_LABELS)


def test_suppression_only_bundle_cannot_establish_clean(tmp_path, no_asn_lookup):
    """Suppression data alone has checked nothing.

    A list of known-good ranges can clear a flag but can never raise one, so a
    bundle holding only suppression lists must not report an address as clean.
    """
    index = AnonymiserIndex(
        build_bundle(tmp_path, lists={"privacy_relay": ["45.45.45.0/24"]})
    )

    result = index.classify(CLEAN)

    assert result["resolved"] is False


def test_partial_coverage_weakens_a_clean_verdict(tmp_path, no_asn_lookup):
    partial = AnonymiserIndex(
        build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    )

    result = partial.classify(CLEAN)

    assert result["labels"] == []
    assert result["resolved"] is True
    # Only one of three detection sources was available.
    assert result["confidence"] < 90


def test_missing_suppression_data_weakens_a_positive_verdict(tmp_path, no_asn_lookup):
    """Without a known-good list, a positive verdict cannot rule out legitimate
    shared egress, so it is reported slightly less confidently."""
    with_suppression = AnonymiserIndex(
        build_bundle(
            tmp_path / "a",
            lists={
                "tor_exit": ["77.77.77.0/24"],
                "commercial_vpn": ["88.88.88.0/24"],
                "datacenter": ["45.45.45.0/24"],
                "privacy_relay": ["10.0.0.0/8"],
                "corporate_egress": ["172.16.0.0/12"],
            },
        )
    )
    without = AnonymiserIndex(
        build_bundle(
            tmp_path / "b",
            lists={
                "tor_exit": ["77.77.77.0/24"],
                "commercial_vpn": ["88.88.88.0/24"],
                "datacenter": ["45.45.45.0/24"],
            },
        )
    )

    assert (
        without.classify(TOR)["confidence"]
        < with_suppression.classify(TOR)["confidence"]
    )


def test_stale_data_weakens_a_positive_verdict(tmp_path, no_asn_lookup, monkeypatch):
    monkeypatch.setattr(local_anon, "IP_DATA_STALE_WARN_DAYS", 45)
    lists = {
        "tor_exit": ["77.77.77.0/24"],
        "commercial_vpn": ["88.88.88.0/24"],
        "datacenter": ["45.45.45.0/24"],
        "privacy_relay": ["10.0.0.0/8"],
        "corporate_egress": ["172.16.0.0/12"],
    }
    fresh = AnonymiserIndex(build_bundle(tmp_path / "fresh", lists=lists))
    stale = AnonymiserIndex(build_bundle(tmp_path / "stale", lists=lists))
    monkeypatch.setattr(fresh, "age_days", lambda: 1)
    monkeypatch.setattr(stale, "age_days", lambda: 400)

    assert stale.classify(TOR)["confidence"] < fresh.classify(TOR)["confidence"]


# -- private addresses -----------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1", "169.254.1.1", "fd00::1"],
)
def test_non_public_addresses_are_classified_without_any_data(ip):
    """Decided before the bundle is consulted, because no data is needed.

    A deployment with no bundle at all still classifies internal traffic
    correctly instead of reporting it as unresolved.
    """
    index = AnonymiserIndex(None)

    result = index.classify(ip)

    assert result["labels"] == ["non_public"]
    assert result["is_vpn"] is False
    assert result["resolved"] is True
    assert result["confidence"] == 100
    assert result["unchecked"] == []


# -- degradation -----------------------------------------------------------


def test_no_bundle_configured_is_unresolved_not_an_error():
    result = AnonymiserIndex(None).classify(CLEAN)

    assert result["resolved"] is False
    assert result["is_vpn"] is False


def test_missing_bundle_directory_is_unresolved(tmp_path):
    result = AnonymiserIndex(str(tmp_path / "absent")).classify(CLEAN)

    assert result["resolved"] is False


def test_corrupt_manifest_is_unresolved(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")

    result = AnonymiserIndex(str(tmp_path)).classify(CLEAN)

    assert result["resolved"] is False


def test_invalid_address_is_unresolved(full_bundle):
    for value in ("", "not-an-ip", "999.999.999.999", "1.2.3.4/24"):
        assert full_bundle.classify(value)["resolved"] is False


def test_missing_list_file_does_not_lose_the_rest_of_the_bundle(tmp_path, no_asn_lookup):
    path = build_bundle(
        tmp_path,
        lists={
            "tor_exit": ["77.77.77.0/24"],
            "commercial_vpn": ["88.88.88.0/24"],
            "datacenter": ["45.45.45.0/24"],
        },
    )
    (tmp_path / "commercial_vpn.txt").unlink()

    index = AnonymiserIndex(path)

    assert index.classify(TOR)["is_vpn"] is True
    assert "commercial_vpn" in index.classify(TOR)["unchecked"]


def test_unrecognised_label_is_ignored(tmp_path, no_asn_lookup, caplog):
    """A bundle newer than the code must not inject labels classify() cannot grade."""
    index = AnonymiserIndex(
        build_bundle(
            tmp_path,
            lists={
                "tor_exit": ["77.77.77.0/24"],
                "some_future_label": ["8.8.4.0/24"],
            },
        )
    )

    result = index.classify(CLEAN)

    assert "some_future_label" not in result["labels"]
    assert "some_future_label" not in result["unchecked"]


# -- reload ----------------------------------------------------------------


def test_bundle_is_reloaded_when_atomically_replaced(tmp_path, no_asn_lookup):
    """A refresh underneath a running engine is picked up.

    Replacement is done by writing beside the live file and renaming over it,
    which is what the bundle builder does and what an operator refreshing a mount
    should do. The rename gives the manifest a new inode, which is the change the
    reload check is keyed on.
    """
    path = build_bundle(tmp_path / "live", lists={"tor_exit": ["77.77.77.0/24"]})
    index = AnonymiserIndex(path, check_interval=0)

    assert index.classify(TOR)["is_vpn"] is True
    assert index.classify("45.45.45.1")["is_vpn"] is False

    staged = build_bundle(tmp_path / "staged", lists={"tor_exit": ["45.45.45.0/24"]})
    (Path(staged) / "tor_exit.txt").replace(Path(path) / "tor_exit.txt")
    (Path(staged) / "manifest.json").replace(Path(path) / "manifest.json")

    assert index.classify("45.45.45.1")["is_vpn"] is True
    assert index.classify(TOR)["is_vpn"] is False


def test_an_in_place_rewrite_of_a_different_size_is_reloaded(tmp_path, no_asn_lookup):
    path = build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    index = AnonymiserIndex(path, check_interval=0)
    assert index.classify(TOR)["is_vpn"] is True

    # A second list makes the manifest a different size, so the change is visible
    # even where the filesystem's mtime granularity is coarse.
    build_bundle(
        tmp_path,
        lists={"tor_exit": ["45.45.45.0/24"], "commercial_vpn": ["88.88.88.0/24"]},
    )

    assert index.classify(TOR)["is_vpn"] is False
    assert index.classify(VPN)["is_vpn"] is True


def test_reload_is_not_detected_by_content_alone(tmp_path, no_asn_lookup):
    """Documents a real limitation rather than asserting it away.

    The change check is (mtime_ns, size, inode), not a content hash: hashing
    multi-megabyte files every interval would cost far more than it is worth. So
    an in-place rewrite that keeps the same size and lands within one mtime tick
    is invisible until the next real change.

    This is not a problem for the shipped refresh paths, which either rename a
    new file into place (new inode) or change the file's size. It would only bite
    an operator overwriting a list in place with a same-length edit.
    """
    path = build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    index = AnonymiserIndex(path, check_interval=0)
    assert index.classify(TOR)["is_vpn"] is True

    stat_before = (Path(path) / "manifest.json").stat()
    # Same number of lists and an equal-length epoch, so the byte count matches.
    build_bundle(
        tmp_path,
        lists={"tor_exit": ["45.45.45.0/24"]},
        build_epoch=int(time.time()),
    )
    stat_after = (Path(path) / "manifest.json").stat()

    unchanged_stamp = (
        stat_before.st_mtime_ns == stat_after.st_mtime_ns
        and stat_before.st_size == stat_after.st_size
        and stat_before.st_ino == stat_after.st_ino
    )
    if not unchanged_stamp:
        pytest.skip("filesystem mtime resolution distinguished the two writes")

    # The old verdict persists, which is the documented consequence.
    assert index.classify(TOR)["is_vpn"] is True


def test_a_broken_replacement_keeps_serving_the_loaded_bundle(tmp_path, no_asn_lookup):
    """Never fail auth because someone truncated a file mid-copy."""
    path = build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    index = AnonymiserIndex(path, check_interval=0)
    assert index.classify(TOR)["is_vpn"] is True

    (tmp_path / "manifest.json").write_text("{ truncated", encoding="utf-8")

    assert index.classify(TOR)["is_vpn"] is True


def test_a_deleted_manifest_keeps_serving_the_loaded_bundle(tmp_path, no_asn_lookup):
    path = build_bundle(tmp_path, lists={"tor_exit": ["77.77.77.0/24"]})
    index = AnonymiserIndex(path, check_interval=0)
    assert index.classify(TOR)["is_vpn"] is True

    (tmp_path / "manifest.json").unlink()

    assert index.classify(TOR)["is_vpn"] is True


# -- reporting -------------------------------------------------------------


def test_age_is_reported_and_never_negative(tmp_path, no_asn_lookup):
    future = AnonymiserIndex(
        build_bundle(tmp_path, lists={"tor_exit": ["10.0.0.0/8"]}, build_epoch=2**32)
    )
    future.ensure_loaded()

    assert future.age_days() == 0


def test_age_is_none_when_the_manifest_omits_it(tmp_path, no_asn_lookup):
    (tmp_path / "tor_exit.txt").write_text("77.77.77.0/24", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"lists": {"tor_exit": "tor_exit.txt"}}), encoding="utf-8"
    )
    index = AnonymiserIndex(str(tmp_path))
    index.ensure_loaded()

    assert index.age_days() is None


def test_has_suppression_data_reflects_the_bundle(tmp_path, no_asn_lookup):
    without = AnonymiserIndex(
        build_bundle(tmp_path / "a", lists={"tor_exit": ["10.0.0.0/8"]})
    )
    without.ensure_loaded()
    assert without.has_suppression_data() is False

    with_data = AnonymiserIndex(
        build_bundle(
            tmp_path / "b",
            lists={"tor_exit": ["10.0.0.0/8"], "privacy_relay": ["45.45.45.0/24"]},
        )
    )
    with_data.ensure_loaded()
    assert with_data.has_suppression_data() is True


def test_startup_warns_when_the_flag_is_on_without_suppression_data(
    tmp_path, no_asn_lookup, monkeypatch, caplog
):
    monkeypatch.setattr(local_anon, "ANON_DATACENTER_IS_VPN", True)
    monkeypatch.setattr(
        local_anon,
        "INDEX",
        AnonymiserIndex(build_bundle(tmp_path, lists={"datacenter": ["45.45.45.0/24"]})),
    )

    caplog.set_level("WARNING")
    local_anon.log_startup_state()

    assert "ANON_DATACENTER_IS_VPN" in caplog.text

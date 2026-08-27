"""IpRangeIndex: CIDR membership, per address family."""

import ipaddress

from src.utils.info_provider.ip_intel.ranges import IpRangeIndex


def addr(text):
    return ipaddress.ip_address(text)


def test_membership_at_and_around_boundaries():
    index = IpRangeIndex.from_lines(["10.0.0.0/24"])

    assert index.contains(addr("10.0.0.0"))  # network address
    assert index.contains(addr("10.0.0.255"))  # broadcast address
    assert index.contains(addr("10.0.0.128"))
    assert not index.contains(addr("9.255.255.255"))
    assert not index.contains(addr("10.0.1.0"))


def test_bare_address_is_a_single_host_range():
    index = IpRangeIndex.from_lines(["203.0.113.5"])

    assert index.contains(addr("203.0.113.5"))
    assert not index.contains(addr("203.0.113.4"))
    assert not index.contains(addr("203.0.113.6"))


def test_non_zero_host_bits_are_accepted():
    # X4BNet and similar feeds ship rows like 1.2.3.4/24. strict=False means we
    # take the enclosing network instead of discarding the row.
    index = IpRangeIndex.from_lines(["10.1.2.3/24"])

    assert index.contains(addr("10.1.2.0"))
    assert index.contains(addr("10.1.2.255"))


def test_malformed_rows_are_skipped_not_fatal():
    index = IpRangeIndex.from_lines(
        [
            "",
            "   ",
            "# a comment",
            "not-an-ip",
            "999.999.999.999/8",
            "10.0.0.0/33",
            "192.0.2.0/24",
        ]
    )

    # The one good row survives; nothing raised.
    assert index.contains(addr("192.0.2.7"))
    assert index.size(4) == 1


def test_comma_separated_rows_take_the_first_field():
    index = IpRangeIndex.from_lines(["192.0.2.0/24,US,Springfield"])

    assert index.contains(addr("192.0.2.7"))


def test_families_are_tracked_separately():
    """The property the honest-unchecked reporting depends on.

    An IPv4-only list must report "no data" for IPv6 rather than "no match", so
    that a v6 client is not silently declared clean by a list that could never
    have contained it.
    """
    v4_only = IpRangeIndex.from_lines(["10.0.0.0/8"])

    assert v4_only.covers_version(4)
    assert not v4_only.covers_version(6)
    # An IPv6 address does not match, and must not be mistaken for a real miss.
    assert not v4_only.contains(addr("2001:db8::1"))

    both = IpRangeIndex.from_lines(["10.0.0.0/8", "2001:db8::/32"])
    assert both.covers_version(4)
    assert both.covers_version(6)
    assert both.contains(addr("2001:db8::1"))
    assert not both.contains(addr("2001:dba::1"))


def test_empty_input_covers_nothing():
    index = IpRangeIndex.from_lines([])

    assert not index.covers_version(4)
    assert not index.covers_version(6)
    assert index.size(4) == 0
    assert not index.contains(addr("10.0.0.1"))


def test_adjacent_and_overlapping_ranges_merge():
    # Merging is what keeps the bisect lookup correct as well as small: an
    # overlapping pair must not shadow part of its own coverage.
    index = IpRangeIndex.from_lines(
        ["10.0.0.0/24", "10.0.1.0/24", "10.0.0.128/25", "10.0.2.0/24"]
    )

    for ip in ("10.0.0.1", "10.0.0.200", "10.0.1.1", "10.0.2.254"):
        assert index.contains(addr(ip)), ip
    assert not index.contains(addr("10.0.3.0"))
    # Four input rows describing one contiguous block collapse to one range.
    assert index.size(4) == 1


def test_lookup_is_correct_across_many_disjoint_ranges():
    # Exercises the bisect path with enough ranges that an off-by-one in the
    # boundary handling would show up.
    lines = [f"10.{n}.0.0/24" for n in range(0, 200, 2)]
    index = IpRangeIndex.from_lines(lines)

    assert index.size(4) == 100
    for n in range(0, 200, 2):
        assert index.contains(addr(f"10.{n}.0.1")), n
    for n in range(1, 200, 2):
        assert not index.contains(addr(f"10.{n}.0.1")), n

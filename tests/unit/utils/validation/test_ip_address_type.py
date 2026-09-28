import pytest
from src.utils.validation.ip_address_type import (
    is_ipv4,
    is_ipv4_cidr,
    is_ipv6,
    validate_ip_input,
)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("192.168.1.1", True),
        ("255.255.255.255", True),
        ("0.0.0.0", True),
        ("300.1.1.1", False),
        ("abcd", False),
        ("::1", False),
    ],
)
def test_is_ipv4(address, expected):
    assert is_ipv4(address) == expected


@pytest.mark.parametrize(
    "network,expected",
    [
        ("192.168.0.0/24", True),
        ("10.0.0.0/8", True),
        ("172.16.0.0/16", True),
        ("192.168.1.1", True),  # technically valid with strict=False
        ("192.168.0.0/33", False),
        ("not_a_cidr", False),
    ],
)
def test_is_ipv4_cidr(network, expected):
    assert is_ipv4_cidr(network) == expected


@pytest.mark.parametrize(
    "address,expected",
    [
        ("::1", True),
        ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", True),
        ("12345::abcd", False),
        ("invalid", False),
        ("192.168.0.1", False),
    ],
)
def test_is_ipv6(address, expected):
    assert is_ipv6(address) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("192.168.1.1", "IPv4"),
        ("10.0.0.0/8", "IPv4/CIDR"),
        ("::1", "IPv6"),
    ],
)
def test_validate_ip_input_valid(value, expected):
    assert validate_ip_input(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        "12345::abcd",
        "192.168.1.256",
        "hello world",
        "",
        {"test", "sa"},
        -2,
        1.0,
    ],
)
def test_validate_ip_input_invalid(value):
    with pytest.raises(ValueError, match=f"Invalid IP input: {value}"):
        validate_ip_input(value)

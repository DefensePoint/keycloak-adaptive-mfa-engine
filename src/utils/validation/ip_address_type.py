import ipaddress


def is_ipv4(address: str) -> bool:
    """
    Returns True if `address` is a valid IPv4 address.
    """
    try:
        ipaddress.IPv4Address(address)
        return True
    except ipaddress.AddressValueError:
        return False


def is_ipv4_cidr(network: str) -> bool:
    """
    Returns True if `network` is a valid IPv4 network in CIDR notation.
    """
    try:
        ipaddress.IPv4Network(network, strict=False)
        return True
    except (ipaddress.NetmaskValueError, ipaddress.AddressValueError):
        return False


def is_ipv6(address: str) -> bool:
    """
    Returns True if `address` is a valid IPv6 address.
    """
    try:
        ipaddress.IPv6Address(address)
        return True
    except ipaddress.AddressValueError:
        return False


def validate_ip_input(value: str) -> str:
    """
    Determines the type of IP input and returns one of:
      - "IPv4"
      - "IPv4/CIDR"
      - "IPv6"
      - raises ValueError if none match
    """
    if is_ipv4(value):
        return "IPv4"
    if is_ipv4_cidr(value):
        return "IPv4/CIDR"
    if is_ipv6(value):
        return "IPv6"
    raise ValueError(f"Invalid IP input: {value}")

"""Resolution goes to local data, and nothing else.

The property worth testing here is negative: no code path in IP intelligence
reaches the network. That is the whole basis of the air-gapped claim, so it is
asserted rather than assumed.
"""

import pytest

from src.utils.info_provider import ip_intel
from src.utils.info_provider.ip_intel.base import (
    ANONYMITY_RESULT_KEYS,
    GEO_RESULT_KEYS,
)


@pytest.fixture
def local_stubs(monkeypatch):
    """Record which local provider was consulted."""
    calls = []

    monkeypatch.setattr(
        ip_intel.local_geo,
        "lookup",
        lambda ip: calls.append(("geo", ip)) or dict.fromkeys(GEO_RESULT_KEYS),
    )
    monkeypatch.setattr(
        ip_intel.local_anon.INDEX,
        "classify",
        lambda ip: calls.append(("anon", ip)) or dict.fromkeys(ANONYMITY_RESULT_KEYS),
    )
    return calls


@pytest.mark.asyncio
async def test_geo_resolves_from_the_local_database(local_stubs):
    await ip_intel.resolve_geo("1.2.3.4")

    assert local_stubs == [("geo", "1.2.3.4")]


@pytest.mark.asyncio
async def test_anonymity_resolves_from_the_local_index(local_stubs):
    await ip_intel.resolve_anonymity("1.2.3.4")

    assert local_stubs == [("anon", "1.2.3.4")]


def test_no_http_client_is_reachable_from_the_package():
    """An air-gap review asks exactly this question.

    Neither ``requests`` nor ``aiohttp`` may be bound in any module of the IP
    intelligence package, so a lookup cannot open a socket even by accident.
    """
    import src.utils.info_provider.ip_intel as package
    from src.utils.info_provider.ip_intel import (
        base,
        centroids,
        local_anon,
        local_geo,
        mmdb,
        ranges,
    )

    for module in (package, base, centroids, local_anon, local_geo, mmdb, ranges):
        names = vars(module)
        assert "requests" not in names, module.__name__
        assert "aiohttp" not in names, module.__name__


def test_the_api_providers_are_gone_not_merely_disabled():
    """A disabled provider still ships its credential handling and outbound call,
    which an air-gapped deployment would then have to argue about."""
    import src.utils.info_provider.ip_intel as package

    assert not hasattr(package, "api_geo")
    assert not hasattr(package, "api_anon")

    with pytest.raises(ImportError):
        from src.utils.info_provider.ip_intel import api_geo  # noqa: F401

    with pytest.raises(ImportError):
        from src.utils.info_provider.ip_intel import api_anon  # noqa: F401


def test_no_api_configuration_remains():
    """The keys, quotas and cache TTLs those providers needed are gone too."""
    from src.core.config import environment

    for name in (
        "IPINFO_TOKEN",
        "IP_HUB_API_KEY",
        "VPN_DAILY_LIMIT",
        "VPN_CACHE_EXPIRATION",
        "GEOLOC_CACHE_EXPIRATION",
        "GEOLOC_LOOKUP_TIMEOUT",
        "VPN_API_COUNT_KEY_TEMPLATE",
        "IP_GEO_PROVIDER",
        "IP_ANON_PROVIDER",
    ):
        assert not hasattr(environment, name), name


def test_startup_reporting_states_that_nothing_calls_out(monkeypatch, caplog):
    monkeypatch.setattr(ip_intel.local_geo, "log_startup_state", lambda: None)
    monkeypatch.setattr(ip_intel.local_anon, "log_startup_state", lambda: None)

    caplog.set_level("INFO")
    ip_intel.log_startup_state()

    assert "no outbound calls" in caplog.text

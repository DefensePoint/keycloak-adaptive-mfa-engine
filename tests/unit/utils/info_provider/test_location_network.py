from datetime import datetime
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


from src.data.model.location_network import LocationNetwork
from src.data.repository.location_network import LocationNetworkRepository
from src.utils.info_provider.location_network import get_cached_location_network_by_hash
from tests.fixture.util import generate_sha3_256_hash


@pytest.mark.asyncio
async def test_returns_location_network_from_cache(mocker):
    loc_net_hash = "a" * 64
    expected_data = {
        "hash": loc_net_hash,
        "geolocation_cluster_label": 1,
        "country": "USA",
        "ip_address": "192.168.1.1",
        "is_vpn_flag": 0,
    }

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=json.dumps(expected_data))
    mocker.patch(
        "src.utils.info_provider.location_network.get_redis", return_value=redis_mock
    )

    result = await get_cached_location_network_by_hash(loc_net_hash)

    assert isinstance(result, LocationNetwork)
    assert result.hash == loc_net_hash
    assert result.country == "USA"
    assert result.ip_address == "192.168.1.1"
    redis_mock.get.assert_awaited_once_with(f"auth:location_network:v1:{loc_net_hash}")


@pytest.mark.asyncio
async def test_returns_location_network_from_db_and_caches_it(mocker):
    loc_net_hash = "context_hash"
    db_obj = LocationNetwork(
        hash=generate_sha3_256_hash(loc_net_hash),
        geolocation_cluster_label=1,
        country="76",
        ip_address="192.168.0.1",
        is_vpn_flag=1,
    )

    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    mocker.patch(
        "src.utils.info_provider.location_network.get_redis", return_value=redis_mock
    )
    mocker.patch.object(
        LocationNetworkRepository,
        "get_location_network_by_hash",
        new=AsyncMock(return_value=db_obj),
    )

    result = await get_cached_location_network_by_hash(loc_net_hash)

    assert result == db_obj
    redis_mock.set.assert_awaited_once()
    redis_mock.set.assert_awaited_once_with(
        name=f"auth:location_network:v1:{loc_net_hash}",
        value=json.dumps(db_obj.to_dict()),
        ex=86400,
    )


@pytest.mark.asyncio
async def test_returns_none_if_not_found_anywhere(mocker):
    loc_net_hash = "d" * 64

    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    mocker.patch(
        "src.utils.info_provider.location_network.get_redis", return_value=redis_mock
    )
    mocker.patch.object(
        LocationNetworkRepository,
        "get_location_network_by_hash",
        new=AsyncMock(return_value=None),
    )

    result = await get_cached_location_network_by_hash(loc_net_hash)

    assert result is None
    redis_mock.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_json_in_cache_triggers_delete(mocker):
    loc_net_hash = "c" * 64

    redis_mock = AsyncMock()
    redis_mock.get.return_value = "invalid json"
    redis_mock.delete = AsyncMock()

    mocker.patch(
        "src.utils.info_provider.location_network.get_redis", return_value=redis_mock
    )
    mocker.patch.object(
        LocationNetworkRepository,
        "get_location_network_by_hash",
        new=AsyncMock(return_value=None),
    )

    result = await get_cached_location_network_by_hash(loc_net_hash)

    assert result is None
    redis_mock.delete.assert_awaited_once_with(
        f"auth:location_network:v1:{loc_net_hash}"
    )

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.data.model.device import Device
from src.data.repository.device import DeviceRepository
from src.utils.info_provider.device import get_cached_device_by_hash
from tests.fixture.util import generate_sha3_256_hash


@pytest.mark.asyncio
async def test_returns_device_from_cache(mocker):
    device_hash = "a" * 64
    expected_data = {
        "hash": device_hash,
        "client": "app",
        "device": "iPhone",
        "system_language": "en",
        "screen_resolution": "1920x1080",
        "operating_system": "iOS",
        "browser": "Safari",
    }

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=json.dumps(expected_data))
    mocker.patch("src.utils.info_provider.device.get_redis", return_value=redis_mock)

    result = await get_cached_device_by_hash(device_hash)

    assert isinstance(result, Device)
    assert result.hash == device_hash
    assert result.device == "iPhone"
    redis_mock.get.assert_awaited_once_with(f"auth:device:v1:{device_hash}")


@pytest.mark.asyncio
async def test_returns_device_from_db_and_caches_it(mocker):
    device_hash = "context_hash"
    db_obj = Device(
        hash=generate_sha3_256_hash(device_hash),
        client="test",
        device="Mac",
        system_language="pt",
        screen_resolution="2560x1440",
        operating_system="macOS",
        browser="Chrome",
        created_at=datetime.now(),
    )

    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    mocker.patch("src.utils.info_provider.device.get_redis", return_value=redis_mock)
    mocker.patch.object(
        DeviceRepository,
        "get_device_by_hash",
        new=AsyncMock(return_value=db_obj),
    )

    result = await get_cached_device_by_hash(device_hash)

    assert result == db_obj
    redis_mock.set.assert_awaited_once_with(
        name=f"auth:device:v1:{device_hash}",
        value=json.dumps(db_obj.to_dict()),
        ex=86400,
    )


@pytest.mark.asyncio
async def test_returns_none_if_not_found_anywhere(mocker):
    device_hash = "c" * 64

    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    mocker.patch("src.utils.info_provider.device.get_redis", return_value=redis_mock)
    mocker.patch.object(
        DeviceRepository,
        "get_device_by_hash",
        new=AsyncMock(return_value=None),
    )

    result = await get_cached_device_by_hash(device_hash)

    assert result is None
    redis_mock.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_json_in_cache_triggers_delete(mocker):
    device_hash = "d" * 64

    redis_mock = AsyncMock()
    redis_mock.get.return_value = "not a valid json"
    redis_mock.delete = AsyncMock()

    mocker.patch("src.utils.info_provider.device.get_redis", return_value=redis_mock)
    mocker.patch.object(
        DeviceRepository,
        "get_device_by_hash",
        new=AsyncMock(return_value=None),
    )

    result = await get_cached_device_by_hash(device_hash)

    assert result is None
    redis_mock.delete.assert_awaited_once_with(f"auth:device:v1:{device_hash}")

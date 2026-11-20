from uuid import uuid4
import pytest
from unittest.mock import AsyncMock, MagicMock


from src.data.factory.device import DeviceFactory
from src.data.schema import DecisionRequest
from src.utils.data_processing.user_agent import UserAgentInfo
from src.core.config.environment import DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION
from src.utils.data_processing.hash import hash_str


@pytest.mark.asyncio
async def test_identify_from_auth_request(mocker):
    request = MagicMock(DecisionRequest)
    request.user_id = uuid4()
    request.group_id = uuid4()
    request.realm_id = uuid4()
    request.ip_address = "192.168.1.1"
    request.client = "client"
    request.user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 5_1 like Mac OS X) AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9B179 Safari/7534.48.3"
    request.cookie = "cookie"
    request.system_language = "en"
    request.screen_resolution = "1920x1080"
    mocked_user_agent_info = UserAgentInfo(request.user_agent)

    attrs = [
        str(request.client),
        str(request.screen_resolution),
        str(request.system_language),
        str(mocked_user_agent_info.get_device()),
        str(mocked_user_agent_info.get_browser_signal(DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION)),
        str(mocked_user_agent_info.get_os_family_major()),
    ]

    content_str = "|".join(attrs)
    mocked_device_hash = hash_str(content_str)

    mock_ensure_device = mocker.patch(
        "src.data.factory.device.DeviceRepository.ensure_device",
        new_callable=AsyncMock,
        return_value=True,
    )

    device_hash = await DeviceFactory.identify_from_auth_request(request)

    assert device_hash == mocked_device_hash
    mock_ensure_device.assert_awaited_once()
    assert mock_ensure_device.await_args.args[0].hash == mocked_device_hash


@pytest.mark.asyncio
async def test_a_known_device_is_still_checked_in_the_database(mocker):
    """The database says whether a device is known, on every login, so a
    database that lost the row gets it back before anything refers to it."""
    request = MagicMock(DecisionRequest)
    request.client = "client"
    request.user_agent = "Mozilla/5.0"
    request.system_language = "en"
    request.screen_resolution = "1920x1080"
    ensure = mocker.patch(
        "src.data.factory.device.DeviceRepository.ensure_device",
        new_callable=AsyncMock,
        return_value=False,
    )

    first = await DeviceFactory.identify_from_auth_request(request)
    second = await DeviceFactory.identify_from_auth_request(request)

    assert first == second
    assert ensure.await_count == 2

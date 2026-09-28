from uuid import uuid4
import pytest
from unittest.mock import AsyncMock, MagicMock


from src.data.factory.network_location import NetworkLocationFactory
from src.data.schema import DecisionRequest
from src.utils.data_processing.user_agent import UserAgentInfo
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
    mocked_geo_info = {
        "lat": 40.7128,
        "long": -74.0060,
        "country_name": "USA",
        "city_name": "New York",
    }
    mocked_vpn_info = {"is_vpn": True}
    mocker.patch(
        "src.data.factory.network_location.get_cached_geo_info",
        new_callable=AsyncMock,
        return_value=mocked_geo_info,
    )
    mocker.patch(
        "src.data.factory.network_location.get_cached_vpn_info",
        new_callable=AsyncMock,
        return_value=mocked_vpn_info,
    )

    attrs = [
        str(request.ip_address),
        str(mocked_vpn_info.get("is_vpn")),
        str(mocked_geo_info.get("lat")),
        str(mocked_geo_info.get("long")),
        str(mocked_geo_info.get("city_name")),
        str(mocked_geo_info.get("country_name")),
    ]

    content_str = "|".join(attrs)
    mocked_network_hash = hash_str(content_str)

    mock_get_network_by_hash = mocker.patch(
        "src.data.factory.network_location.get_cached_location_network_by_hash",
        new_callable=AsyncMock,
        return_value=None,
    )
    mock_create_network = mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.create_location_network",
        new_callable=AsyncMock,
        return_value=None,
    )

    device_hash = await NetworkLocationFactory.identify_from_auth_request(request)

    assert device_hash == device_hash
    mock_get_network_by_hash.assert_awaited_once_with(mocked_network_hash)
    mock_create_network.assert_awaited_once()

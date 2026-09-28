import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.data.factory.auth_process import AuthProcessFactory
from src.data.model import AuthProcess
from src.data.schema import DecisionRequest

from src.utils.data_processing.user_agent import UserAgentInfo
from src.core.config.environment import DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION


@pytest.mark.asyncio
async def test_build_preauth_obj(mocker):
    request = MagicMock(DecisionRequest)
    request.user_id = uuid4()
    request.event_id = uuid4()
    request.ip_address = "192.168.1.1"
    request.client = "client"
    request.user_agent = "Mozilla/5.0"
    request.cookie = "cookie"
    request.system_language = "en"
    request.screen_resolution = "1920x1080"
    request.group_id = uuid4()
    request.realm_id = uuid4()

    params_id = uuid4()
    auth_context = {"key": "value"}
    risk_eval_vars = {"risk": "high"}
    risk_decision = "deny"
    device_credibility = 0.4
    net_loc_credibility = 0.2

    mocked_device_hash = "device_hash"
    mocked_network_location_hash = "network_location_hash"
    mocked_auth_context_hash = "auth_context_hash"
    mock_hash = mocker.Mock()
    mock_hash.hexdigest.return_value = mocked_auth_context_hash

    mocker.patch("hashlib.sha3_256", return_value=mock_hash)
    mocker.patch(
        "src.data.factory.device.DeviceFactory.identify_from_auth_request",
        return_value=mocked_device_hash,
    )
    mocker.patch(
        "src.data.factory.network_location.NetworkLocationFactory.identify_from_auth_request",
        return_value=mocked_network_location_hash,
    )

    auth_process = await AuthProcessFactory.build_preauth_obj(
        request,
        params_id,
        auth_context,
        risk_eval_vars,
        risk_decision,
        device_credibility,
        net_loc_credibility,
    )

    assert auth_process.parameters_config_id == params_id
    assert auth_process.final_status == "pre-auth"
    assert auth_process.user_id == request.user_id
    assert auth_process.realm_id == request.realm_id
    assert auth_process.id == request.event_id
    assert auth_process.device_info_hash == mocked_device_hash
    assert auth_process.network_location_hash == mocked_network_location_hash
    assert auth_process.auth_context_hash == mocked_auth_context_hash
    assert auth_process.auth_context_json == auth_context
    assert auth_process.risk_eval_vars == risk_eval_vars
    assert auth_process.pre_auth_risk_decision == risk_decision


@pytest.mark.asyncio
async def test_build_initial_event_dict(mocker):
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

    mocked_geo_info = {
        "lat": 40.7128,
        "long": -74.0060,
        "country_name": "USA",
        "city_name": "New York",
    }
    mocked_vpn_info = {"is_vpn": True}
    mocker.patch(
        "src.data.factory.auth_process.get_cached_geo_info",
        new_callable=AsyncMock,
        return_value=mocked_geo_info,
    )
    mocker.patch(
        "src.data.factory.auth_process.get_cached_vpn_info",
        new_callable=AsyncMock,
        return_value=mocked_vpn_info,
    )

    mocked_user_agent_info = UserAgentInfo(request.user_agent)
    event_dict = await AuthProcessFactory.build_initial_event_dict(request)

    assert event_dict["client"] == request.client
    assert event_dict["agent_info_str"] == str(mocked_user_agent_info.get_detailed())
    assert event_dict["ip_address"] == request.ip_address
    assert event_dict["user_id"] == request.user_id
    assert event_dict["group_id"] == request.group_id
    assert event_dict["realm_id"] == request.realm_id
    assert event_dict["device"] == mocked_user_agent_info.get_device()
    assert (
        event_dict["operating_system"]
        == mocked_user_agent_info.get_operating_system_family()
    )
    assert event_dict["browser"] == mocked_user_agent_info.get_browser_signal(
        DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION
    )
    assert event_dict["cookie"] == request.cookie
    assert event_dict["lat"] == mocked_geo_info["lat"]
    assert event_dict["long"] == mocked_geo_info["long"]
    assert event_dict["is_vpn"] == mocked_vpn_info["is_vpn"]
    assert event_dict["system_language"] == request.system_language
    assert event_dict["screen_resolution"] == request.screen_resolution
    assert event_dict["country_name"] == mocked_geo_info["country_name"]
    assert event_dict["city_name"] == mocked_geo_info["city_name"]

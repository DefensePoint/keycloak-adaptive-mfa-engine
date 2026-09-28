from src.data.schema import DecisionRequest
from src.data.model import AuthProcess
from src.data.factory import DeviceFactory, NetworkLocationFactory, AuthContextFactory

from src.utils.data_processing.user_agent import UserAgentInfo

from src.utils.info_provider.vpn import get_cached_vpn_info
from src.utils.info_provider.geoloc import get_cached_geo_info

from src.utils.data_processing.hash import hash_str
from src.core.config.environment import DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION

import asyncio

from datetime import datetime
from uuid import UUID

import logging


class AuthProcessFactory:

    @staticmethod
    async def build_preauth_obj(
        request: DecisionRequest,
        params_id,
        auth_context,
        risk_eval_vars,
        risk_decision,
        device_credibility,
        net_loc_credibility,
    ) -> AuthProcess:
        _obj = AuthProcess()

        _obj.parameters_config_id = params_id
        _obj.final_status = str("pre-auth")

        _obj.user_id = request.user_id
        _obj.id = request.event_id
        # Trusted because decision_route.enforce_tenant() already rejected any
        # request whose realm_id does not match the caller's verified token realm
        # before this factory ever runs — never take realm from elsewhere.
        _obj.realm_id = request.realm_id

        _obj.device_info_hash, _obj.network_location_hash = await asyncio.gather(
            DeviceFactory.identify_from_auth_request(request),
            NetworkLocationFactory.identify_from_auth_request(request),
        )

        _obj.device_credibility = device_credibility
        _obj.net_loc_credibility = net_loc_credibility

        _str = str(str(_obj.device_info_hash) + str(_obj.network_location_hash))
        _auth_ctx_hash = hash_str(_str)

        _obj.auth_context_hash = _auth_ctx_hash
        _obj.auth_context_json = auth_context

        _obj.risk_eval_vars = risk_eval_vars
        _obj.pre_auth_risk_decision = risk_decision

        return _obj

    @staticmethod
    async def build_initial_event_dict(request: DecisionRequest) -> dict:

        current_time = datetime.timestamp(datetime.now()) * 1000
        agent_info = UserAgentInfo(request.user_agent)

        geo_info, vpn_info = await asyncio.gather(
            get_cached_geo_info(request.ip_address),
            get_cached_vpn_info(request.ip_address),
        )

        return {
            "id": None,
            "event_time": current_time,
            "client": request.client,
            "agent_info_str": str(agent_info.get_detailed()),
            "ip_address": request.ip_address,
            "user_id": request.user_id,
            "group_id": request.group_id,
            "realm_id": request.realm_id,
            "device": agent_info.get_device(),
            "operating_system": agent_info.get_operating_system_family(),
            "browser": agent_info.get_browser_signal(
                DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION
            ),
            "cookie": request.cookie,
            "lat": geo_info.get("lat"),
            "long": geo_info.get("long"),
            "mobile": None,
            "mobile_lat": None,
            "mobile_long": None,
            "mobile_status": None,
            "is_vpn": vpn_info.get("is_vpn", False),
            "system_language": request.system_language,
            "screen_resolution": request.screen_resolution,
            "country_name": geo_info.get("country_name"),
            "city_name": geo_info.get("city_name"),
        }

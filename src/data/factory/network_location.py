from src.data.schema import DecisionRequest, AuthContextSchema
from src.utils.data_processing.hash import hash_str

from src.utils.info_provider.location_network import get_cached_location_network_by_hash
from src.utils.info_provider.vpn import get_cached_vpn_info
from src.utils.info_provider.geoloc import get_cached_geo_info

from src.data.repository import LocationNetworkRepository
from src.data.model import LocationNetwork

import asyncio

import logging


class NetworkLocationFactory:

    @staticmethod
    async def identify_from_auth_request(
        request: DecisionRequest | AuthContextSchema,
    ) -> str:
        geo_info, vpn_info = await asyncio.gather(
            get_cached_geo_info(request.ip_address),
            get_cached_vpn_info(request.ip_address),
        )

        attrs = [
            str(request.ip_address),
            str(vpn_info.get("is_vpn")),
            str(geo_info.get("lat")),
            str(geo_info.get("long")),
            str(geo_info.get("city_name")),
            str(geo_info.get("country_name")),
        ]

        content_str = "|".join(attrs)
        location_hash = hash_str(content_str)

        existing_net_loc = await get_cached_location_network_by_hash(location_hash)

        if not existing_net_loc:
            new_location = LocationNetwork(
                hash=location_hash,
                geolocation_cluster_label=0,
                country=str(geo_info.get("country_name")),
                ip_address=request.ip_address,
                is_vpn_flag=int(vpn_info.get("is_vpn", 0)),
            )
            await LocationNetworkRepository.create_location_network(new_location)
            logging.info(f"Created new net_loc object | hash {location_hash}")

        return location_hash

from src.data.schema import DecisionRequest, AuthContextSchema
from src.utils.data_processing.hash import hash_str

from src.utils.info_provider.location_network import (
    forget_cached_location_network,
    get_cached_location_network_by_hash,
)
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
        lat, long = _coordinates(geo_info)

        if not existing_net_loc:
            new_location = LocationNetwork(
                hash=location_hash,
                geolocation_cluster_label=0,
                country=str(geo_info.get("country_name")),
                ip_address=request.ip_address,
                is_vpn_flag=int(vpn_info.get("is_vpn", 0)),
                lat=lat,
                long=long,
            )
            await LocationNetworkRepository.create_location_network(new_location)
            logging.info(f"Created new net_loc object | hash {location_hash}")
        elif lat is not None and existing_net_loc.lat is None and existing_net_loc.long is None:
            # A row written before location_network had coordinates, or a copy
            # of it cached before it was filled. The hash covers the
            # coordinates, so these are the row's own. The cached copy goes
            # either way, so a row filled already is not updated again on every
            # login until it expires.
            await LocationNetworkRepository.set_coordinates_if_missing(
                location_hash, lat, long
            )
            await forget_cached_location_network(location_hash)

        return location_hash


def _coordinates(geo_info: dict) -> tuple[float | None, float | None]:
    """The address's coordinates, or none when the lookup could not place it.

    The lookup reports an unplaced address as 0,0; stored as such, a login from
    a private address would sit in the Gulf of Guinea.
    """
    lat, long = geo_info.get("lat"), geo_info.get("long")
    if lat is None or long is None or (lat == 0 and long == 0):
        return None, None
    return float(lat), float(long)

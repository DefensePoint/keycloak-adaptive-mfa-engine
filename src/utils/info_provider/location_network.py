import json
import logging
from typing import Optional
from src.core.config.environment import LOCATION_NETWORK_KEY_TEMPLATE
from src.core.redis import get_redis
from src.data.model.location_network import LocationNetwork
from src.data.repository.location_network import LocationNetworkRepository


REDIS_LOCATION_NETWORK_TTL_SECONDS = 86400  # 24Z hour


async def get_cached_location_network_by_hash(
    loc_net_hash: str,
) -> Optional[LocationNetwork]:
    logging.info(f"Getting cached location network {loc_net_hash}")

    redis_client = get_redis()
    loc_net_key = LOCATION_NETWORK_KEY_TEMPLATE.format(loc_net_hash)

    cached = await redis_client.get(loc_net_key)
    if cached:
        try:
            data = json.loads(cached)
            return LocationNetwork(**data)
        except Exception as e:
            await redis_client.delete(loc_net_key)
            logging.error(f"Error on loading location network json {e}")

    logging.debug("Cache location network not found. Requesting from database")
    db_location = await LocationNetworkRepository.get_location_network_by_hash(
        loc_net_hash
    )

    if db_location:
        logging.debug(f"LocationNetwork entity found hash: {db_location.hash}")
        await redis_client.set(
            name=loc_net_key,
            value=json.dumps(db_location.to_dict()),
            ex=REDIS_LOCATION_NETWORK_TTL_SECONDS,
        )
        return db_location

    logging.debug("Network Location record not found!")
    return None

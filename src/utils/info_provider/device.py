import json
import logging
from typing import Optional
from src.core.config.environment import DEVICE_KEY_TEMPLATE
from src.data.model.device import Device
from src.data.repository.device import DeviceRepository
from src.core.redis import get_redis


REDIS_DEVICE_TTL_SECONDS = 86400  # 24Z hour


async def get_cached_device_by_hash(
    device_hash: str,
) -> Optional[Device]:
    logging.info(f"Getting cached device {device_hash}")

    redis_client = get_redis()
    device_key = DEVICE_KEY_TEMPLATE.format(device_hash)

    cached = await redis_client.get(device_key)
    if cached:
        try:
            data = json.loads(cached)
            return Device(**data)
        except Exception as e:
            await redis_client.delete(device_key)
            logging.error(f"Error on loading device json {e}")

    logging.debug("Cache device not found. Requesting from database")
    db_location = await DeviceRepository.get_device_by_hash(device_hash)

    if db_location:
        logging.debug(f"Device entity found hash: {db_location.hash}")
        await redis_client.set(
            name=device_key,
            value=json.dumps(db_location.to_dict()),
            ex=REDIS_DEVICE_TTL_SECONDS,
        )
        return db_location

    logging.debug("Device record not found!")
    return None

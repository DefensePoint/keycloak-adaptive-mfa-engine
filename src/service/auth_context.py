import asyncio
from src.data.schema import AuthContextSchema, HashResponseSchema
from src.data.factory import DeviceFactory, NetworkLocationFactory

from src.utils.data_processing.hash import hash_str

import logging


class AuthContextService:

    def __init__(self, request: AuthContextSchema) -> None:
        self.request = request

    async def __call__(self) -> HashResponseSchema:
        return await self.__process()

    async def __process(self) -> HashResponseSchema:
        device_hash, net_location_hash = await asyncio.gather(
            DeviceFactory.identify_from_auth_request(self.request),
            NetworkLocationFactory.identify_from_auth_request(self.request),
        )

        _str = str(str(device_hash) + str(net_location_hash))
        _hash = hash_str(_str)

        logging.debug(f"Authentication context hash | {_hash}")

        return HashResponseSchema(hash=_hash)

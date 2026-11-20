"""
# Device Repository
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import DB
from src.data.model import Device


class DeviceRepository:
    """
    # Device Repository

    Provides an asynchronous interface to interact with the **device** table
    using SQLAlchemy. Each method uses an `async_sessionmaker` to manage session
    scope safely within `async with` blocks.
    """

    @staticmethod
    async def create_device(device: Device) -> Device:
        """
        Inserts a new **Device** record into the database, unless a record with
        the same hash already exists.

        Two first logins from the same new device can both find no record and
        insert it at the same moment. The one that loses the race gets the
        record the other stored, instead of failing on the primary key.

        **Parameters**
        - `device`: The **Device** instance to persist.

        **Returns**
        - The stored **Device**: the new one, or the one that already existed.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            session.add(device)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.get(Device, device.hash)
                if existing is None:
                    raise
                return existing
            await session.refresh(device)
            return device

    @staticmethod
    async def ensure_device(device: Device) -> bool:
        """
        Makes sure a **Device** record with this hash exists in the database,
        adding it when it is missing. A record that exists is left as it is.

        The database decides, not a cache: a hash that names no record (after
        the database was restored, swapped or reset) gets its record again, so
        the rows that refer to it can be stored. A known device costs one read
        by primary key. Two first logins from the same new device that both
        find no record are handled by `create_device`.

        **Parameters**
        - `device`: The **Device** to store when no record has its hash.

        **Returns**
        - True when the record was added, False when it already existed.
        """
        if await DeviceRepository.get_device_by_hash(device.hash) is not None:
            return False
        return await DeviceRepository.create_device(device) is device

    @staticmethod
    async def get_device_by_hash(hash_value: str) -> Device | None:
        """
        Retrieves a **Device** record by its unique hash value.

        **Parameters**
        - `hash_value`: The unique hash identifying the **Device** record.

        **Returns**
        - The matching **Device**, or `None` if no record is found.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(Device).where(Device.hash == hash_value)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def list_devices(limit: int | None = None) -> List[Device]:
        """
        Fetches a list of **Device** records from the database.

        **Parameters**
        - `limit`: Maximum number of records to retrieve. Defaults to None

        **Returns**
        - A list of **Device** instances.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            if limit is not None and limit > 0:
                stmt = select(Device).limit(limit)
            else:
                stmt = select(Device)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def update_device(device: Device) -> Device:
        """
        Updates an existing **Device** record in the database.

        **Parameters**
        - `device`: The **Device** instance containing updated fields.

        **Returns**
        - The updated **Device** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            merged_device = await session.merge(device)
            await session.commit()
            await session.refresh(merged_device)
            return merged_device

    @staticmethod
    async def delete_device(device: Device) -> None:
        """
        Removes a **Device** record from the database.

        **Parameters**
        - `device`: The **Device** instance to be deleted.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            device_to_delete = await session.merge(device)
            await session.delete(device_to_delete)
            await session.commit()

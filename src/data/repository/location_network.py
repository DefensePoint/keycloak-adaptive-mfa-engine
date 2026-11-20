"""
# LocationNetwork Model
"""

from typing import List

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import DB
from src.data.model import LocationNetwork


class LocationNetworkRepository:
    """
    # LocationNetwork Repository

    Provides an asynchronous interface for interacting with the **location_network** table
    using SQLAlchemy. Each method uses an `async_sessionmaker` to properly manage session
    scope within an `async with` block.
    """

    @staticmethod
    async def create_location_network(loc_net: LocationNetwork) -> LocationNetwork:
        """
        Inserts a new **LocationNetwork** record into the database, unless a
        record with the same hash already exists.

        Two first logins from the same new network can both find no record and
        insert it at the same moment. The one that loses the race gets the
        record the other stored, instead of failing on the primary key.

        **Parameters**
        - `loc_net`: The **LocationNetwork** instance to persist.

        **Returns**
        - The stored **LocationNetwork**: the new one, or the one that already existed.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            session.add(loc_net)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.get(LocationNetwork, loc_net.hash)
                if existing is None:
                    raise
                return existing
            await session.refresh(loc_net)
            return loc_net

    @staticmethod
    async def get_location_network_by_hash(
        hash_value: str,
    ) -> LocationNetwork | None:
        """
        Retrieves a **LocationNetwork** record by its unique hash value.

        **Parameters**
        - `hash_value`: The unique hash identifying the **LocationNetwork** record.

        **Returns**
        - The matching **LocationNetwork**, or `None` if no record is found.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(LocationNetwork).where(LocationNetwork.hash == hash_value)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def list_location_networks(limit: int | None = None) -> List[LocationNetwork]:
        """
        Fetches a list of **LocationNetwork** records from the database.

        **Parameters**
        - `limit`: Maximum number of records to retrieve. Defaults to None.

        **Returns**
        - A list of **LocationNetwork** instances.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            if limit is not None and limit > 0:
                stmt = select(LocationNetwork).limit(limit)
            else:
                stmt = select(LocationNetwork)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def update_location_network(loc_net: LocationNetwork) -> LocationNetwork:
        """
        Updates an existing **LocationNetwork** record in the database.

        **Parameters**
        - `loc_net`: The **LocationNetwork** instance containing updated fields.

        **Returns**
        - The updated **LocationNetwork** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            merged_loc_net = await session.merge(loc_net)
            await session.commit()
            await session.refresh(merged_loc_net)
            return merged_loc_net

    @staticmethod
    async def ensure_location_network(loc_net: LocationNetwork) -> str:
        """
        Makes sure a **LocationNetwork** record with this hash exists in the
        database, adding it when it is missing. A record that exists is left as
        it is, except that a record written before it had coordinates gets
        those of `loc_net`.

        The database decides, not a cache: a hash that names no record (after
        the database was restored, swapped or reset) gets its record again, so
        the rows that refer to it can be stored. A known network costs one read
        by primary key. Two first logins from the same new network that both
        find no record are handled by `create_location_network`.

        **Parameters**
        - `loc_net`: The **LocationNetwork** to store when no record has its hash.

        **Returns**
        - "created" when the record was added, "filled" when an existing record
          got its coordinates, "kept" when the existing record was left as it is.
        """
        existing = await LocationNetworkRepository.get_location_network_by_hash(loc_net.hash)
        if existing is None:
            stored = await LocationNetworkRepository.create_location_network(loc_net)
            if stored is loc_net:
                return "created"
            existing = stored
        if (
            loc_net.lat is not None
            and loc_net.long is not None
            and existing.lat is None
            and existing.long is None
            # The hash covers the coordinates, so these are the row's own.
            and await LocationNetworkRepository.set_coordinates_if_missing(
                loc_net.hash, loc_net.lat, loc_net.long
            )
        ):
            return "filled"
        return "kept"

    @staticmethod
    async def set_coordinates_if_missing(loc_net_hash: str, lat: float, long: float) -> bool:
        """
        Gives a **LocationNetwork** row written before it had coordinates its
        coordinates. A row that has them is left as it is.

        **Returns**
        - True when the row was updated.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            result = await session.execute(
                update(LocationNetwork)
                .where(
                    LocationNetwork.hash == loc_net_hash,
                    LocationNetwork.lat.is_(None),
                    LocationNetwork.long.is_(None),
                )
                .values(lat=lat, long=long)
            )
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def delete_location_network(loc_net: LocationNetwork) -> None:
        """
        Removes a **LocationNetwork** record from the database.

        **Parameters**
        - `loc_net`: The **LocationNetwork** instance to be deleted.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            loc_net_to_delete = await session.merge(loc_net)
            await session.delete(loc_net_to_delete)
            await session.commit()

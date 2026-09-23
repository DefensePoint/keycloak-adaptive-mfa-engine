"""
# AuthEvent Repository
"""

from typing import List
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import DB
from src.data.model import AuthEvent


class AuthEventRepository:
    """
    An asynchronous interface to interact with the **auth_event** table
    using SQLAlchemy. Each method uses an `async_sessionmaker` to manage session
    scope safely within `async with` blocks.
    """

    @staticmethod
    async def create_auth_event(event: AuthEvent) -> AuthEvent:
        """
        Inserts a new **AuthEvent** record into the database.

        **Parameters**
        - `event`: The **AuthEvent** instance to persist.

        **Returns**
        - The newly created **AuthEvent** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    @staticmethod
    async def get_auth_event_by_id(event_id) -> AuthEvent | None:
        """
        Retrieves an **AuthEvent** record by its unique ID.

        **Parameters**
        - `event_id`: The unique ID (UUID) identifying the **AuthEvent** record.

        **Returns**
        - The matching **AuthEvent**, or `None` if no record is found.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(AuthEvent).where(AuthEvent.id == event_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def list_auth_events(limit: int | None = None) -> List[AuthEvent]:
        """
        Fetches a list of **AuthEvent** records from the database.

        **Parameters**
        - `limit`: Maximum number of records to retrieve. Defaults to None

        **Returns**
        - A list of **AuthEvent** instances.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            if limit is not None and limit > 0:
                stmt = select(AuthEvent).limit(limit)
            else:
                stmt = select(AuthEvent)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def update_auth_event(event: AuthEvent) -> AuthEvent:
        """
        Updates an existing **AuthEvent** record in the database.

        **Parameters**
        - `event`: The **AuthEvent** instance containing updated fields.

        **Returns**
        - The updated **AuthEvent** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            merged_event = await session.merge(event)
            await session.commit()
            await session.refresh(merged_event)
            return merged_event

    @staticmethod
    async def delete_auth_event(event: AuthEvent) -> None:
        """
        Removes an **AuthEvent** record from the database.

        **Parameters**
        - `event`: The **AuthEvent** instance to be deleted.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            event_to_delete = await session.merge(event)
            await session.delete(event_to_delete)
            await session.commit()

    @staticmethod
    async def get_events_for_process(
        process_id,
        limit: int | None = None,
        date_limit: datetime | None = None,
    ) -> List[AuthEvent]:
        """
        Retrieves **AuthEvent** records for a given authentication process. This
        method supports limiting by record count or by a cutoff date.

        **Parameters**
        - `process_id`: The UUID identifying the `auth_process`.
        - `limit`: An optional integer specifying the maximum number of records to fetch.
        - `date_limit`: An optional `datetime` specifying the earliest event time to include.

        **Returns**
        - A list of **AuthEvent** instances matching the criteria.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(AuthEvent).where(AuthEvent.auth_process == process_id)

            if date_limit:
                stmt = stmt.where(AuthEvent.event_time >= date_limit)
            if limit is not None:
                stmt = stmt.limit(limit)

            stmt = stmt.order_by(AuthEvent.event_time.desc())

            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_events_for_user(
        user_id,
        realm_id: str,
        limit: int | None = None,
        date_limit: datetime | None = None,
    ) -> List[AuthEvent]:
        """
        Retrieves **AuthEvent** records for a given user within a single
        realm/tenant. This method supports restricting the record count or
        filtering by a cutoff date.

        **Parameters**
        - `user_id`: The UUID identifying the user.
        - `realm_id`: The realm/tenant the caller was authenticated against. Required
          so one tenant's token can never read another tenant's audit events for a
          guessed or coincidental `user_id` — currently unused (no call sites), kept
          required so a future caller cannot be wired up unscoped by accident.
        - `limit`: An optional integer specifying the maximum number of records to fetch.
        - `date_limit`: An optional `datetime` specifying the earliest event time to include.

        **Returns**
        - A list of **AuthEvent** instances matching the criteria.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(AuthEvent).where(
                AuthEvent.user_id == user_id,
                AuthEvent.realm_id == realm_id,
            )

            if date_limit:
                stmt = stmt.where(AuthEvent.event_time >= date_limit)
            if limit is not None:
                stmt = stmt.limit(limit)

            stmt = stmt.order_by(AuthEvent.event_time.desc())

            result = await session.execute(stmt)
            return result.scalars().all()

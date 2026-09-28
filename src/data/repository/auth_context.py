"""
# AuthContext Repository
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import DB
from src.data.model import AuthContext


class AuthContextRepository:
    """
    # AuthContext Repository

    Provides an asynchronous interface for interacting with the **auth_context** table
    using SQLAlchemy. Each method uses an `async_sessionmaker` to manage session scope
    safely within `async with` blocks.
    """

    @staticmethod
    async def create_context(context: AuthContext) -> AuthContext:
        """
        Inserts a new **AuthContext** record into the database.

        **Parameters**
        - `context`: The **AuthContext** instance to persist.

        **Returns**
        - The newly created **AuthContext** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            session.add(context)
            await session.commit()
            await session.refresh(context)
            return context

    @staticmethod
    async def get_context_by_hash(hash_value: str) -> AuthContext | None:
        """
        Retrieves an **AuthContext** record by its unique hash value.

        **Parameters**
        - `hash_value`: The unique hash identifying the **AuthContext** record.

        **Returns**
        - The matching **AuthContext**, or `None` if no record is found.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            stmt = select(AuthContext).where(AuthContext.hash == hash_value)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def list_contexts(limit: int | None = None) -> List[AuthContext]:
        """
        Fetches a list of **AuthContext** records from the database.

        **Parameters**
        - `limit`: Maximum number of records to retrieve. Defaults to None.

        **Returns**
        - A list of **AuthContext** instances.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            if limit is not None and limit > 0:
                stmt = select(AuthContext).limit(limit)
            else:
                stmt = select(AuthContext)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def update_context(context: AuthContext) -> AuthContext:
        """
        Updates an existing **AuthContext** record in the database.

        **Parameters**
        - `context`: The **AuthContext** instance containing updated fields.

        **Returns**
        - The updated **AuthContext** with refreshed state.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            merged_context = await session.merge(context)
            await session.commit()
            await session.refresh(merged_context)
            return merged_context

    @staticmethod
    async def delete_context(context: AuthContext) -> None:
        """
        Removes an **AuthContext** record from the database.

        **Parameters**
        - `context`: The **AuthContext** instance to be deleted.
        """
        async_session = DB.get_session()
        if not isinstance(async_session, async_sessionmaker):
            raise ValueError("No async database session available")

        async with async_session() as session:
            context_to_delete = await session.merge(context)
            await session.delete(context_to_delete)
            await session.commit()

import logging

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.core.config.environment import DATABASE_URL


class PostgreSQLConnection:

    def __init__(self, url: str = DATABASE_URL, async_engine: bool = True):
        if async_engine:
            async_url = url.replace("postgresql://", "postgresql+asyncpg://")
            self.engine = create_async_engine(async_url, future=True)
            self.Session = async_sessionmaker(
                bind=self.engine, class_=AsyncSession, expire_on_commit=False
            )
        else:
            raise ValueError("Async ORM required")

    def get_session(
        self,
    ) -> async_sessionmaker[AsyncSession]:
        if not hasattr(self, "Session"):
            raise ValueError("No database session available")
        return self.Session


class DbService:
    client = None

    @classmethod
    def get_singleton(cls):
        if cls.client is None:
            cls.client = PostgreSQLConnection(async_engine=True)
            logging.info("Database connection rules singleton initialized at startup!")
        return cls.client


def get_db():
    return DbService.get_singleton()


DB = DbService.get_singleton()

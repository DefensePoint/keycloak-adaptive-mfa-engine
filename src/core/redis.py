import redis.asyncio as redis
import os


class RedisService:
    client = None

    @classmethod
    def get_singleton(cls):
        if cls.client is None:
            cls.client = redis.Redis(
                host=os.getenv("REDIS_HOST", "redis"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                decode_responses=True,
            )
        return cls.client


def get_redis():
    return RedisService.get_singleton()

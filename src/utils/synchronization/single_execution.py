import asyncio
import logging
from functools import wraps

from src.core.redis import get_redis


def enforce_single_execution(lock_key: str, timeout: int = 60, block: bool = True):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            redis = await get_redis()

            async def acquire_lock():
                """Try to acquire a Redis lock."""
                return await redis.set(
                    f"dist_mutex:{lock_key}", "LOCKED", ex=timeout, nx=True
                )

            async def release_lock():
                """Release the Redis lock."""
                await redis.delete(f"dist_mutex:{lock_key}")

            lock_acquired = await acquire_lock()

            if lock_acquired:
                try:
                    return await func(*args, **kwargs)
                finally:
                    await release_lock()
            else:
                if block:
                    logging.info(
                        f"Another worker is running `{func.__name__}`. Waiting..."
                    )
                    while await redis.get(lock_key):
                        await asyncio.sleep(1)
                    logging.info(
                        f"`{func.__name__}` completed by another worker. Proceeding."
                    )
                else:
                    logging.info(
                        f"Another worker is running `{func.__name__}`. Skipping execution."
                    )

        return wrapper

    return decorator

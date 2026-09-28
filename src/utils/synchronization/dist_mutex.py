import functools
import logging
from typing import Callable
import uuid
import time
import asyncio

from datetime import timedelta

from src.core.exception import TimeOutException
from src.core.redis import get_redis


def synchronize_with_distributed_mutex(
    lock_id: str,
    prefix: str = "dist_mutex",
    mutex_timeout: float = 2.1,
    max_wait_time: float = 2.7,
    sleep_interval: float = 0.1,
) -> Callable:
    """
    A decorator to provide distributed mutual exclusion (mutex) using Redis.

    This decorator ensures that a function is executed in a distributed environment
    without overlapping executions. It uses a Redis-backed locking mechanism to
    guarantee that only one instance of the decorated function can run at a time
    for the given lock key (`lock_id`).

    Args:
        lock_id (str): The unique identifier for the distributed lock.
        prefix (str, optional): A prefix to add to the lock key in Redis.
            Defaults to "dist_mutex".
        mutex_timeout (float, optional): The time (in seconds) for which the
            lock is held before expiring. Defaults to 2.1 seconds.
        max_wait_time (float, optional): The maximum time (in seconds) to wait
            to acquire the lock before raising a `TimeOutException`. Defaults
            to 2.7 seconds.
        sleep_interval (float, optional): The interval (in seconds) between
            attempts to acquire the lock. Defaults to 0.1 seconds.

    Returns:
        Callable: A decorator function that wraps the target function, ensuring
            it runs under the distributed lock.

    Raises:
        TimeOutException: Raised if the lock cannot be acquired within
            `max_wait_time`.

    ## Example Usage (user level):

    ```python
    import asyncio
    from src.synchronization import synchronize_with_distributed_mutex

    @synchronize_with_distributed_mutex(lock_id=some_user_uuid)
    async def example_task(some_user_uuid):
        print("Running task...")
        await asyncio.sleep(1)
        print("Task completed.")

    async def main():
        ''' Synchronizes operations at user level, across multiple servers '''
        user_making_request = str(uuid.uuid4())
        await asyncio.gather(
            example_task(user_making_request),  # Task 1
            example_task(user_making_request),  # Task 2 (will wait for the
                                                # first to release the lock)
            example_task(str(uuid.uuid4()))     # Task 3 (runs in parallel)
        )

    asyncio.run(main())
    ```

    ## Example Usage (global level):

    ```python
    import asyncio
    from src.synchronization import synchronize_with_distributed_mutex

    @synchronize_with_distributed_mutex(lock_id='critical_operation')
    async def example_task():
        print("Running task...")
        await asyncio.sleep(1)
        print("Task completed.")

    async def main():
        ''' Synchronizes operations at a global level, across multiple servers '''
        await asyncio.gather(
            example_task(),  # Task 1
            example_task(),  # Task 2 (will wait for the first to release the lock)
        )

    asyncio.run(main())
    ```

    # Notes:
    - Ensure that the Redis connection pool is properly configured and available.
    - This decorator supports only asynchronous functions (`async def`).
      Synchronous functions are not supported.
    """

    def decorator(func):
        redis = get_redis()
        _mutex_timeout = timedelta(seconds=mutex_timeout)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            mutex_key = f"{prefix}:{lock_id}"
            mutex_value = str(uuid.uuid4())

            start_time = time.time()
            acquired = False

            # Attempt to acquire the lock (distributed mutex)
            while not acquired:
                try:
                    acquired = await redis.set(
                        mutex_key,
                        mutex_value,
                        ex=_mutex_timeout,
                        nx=True,  # Only set if key does not exist
                    )
                except Exception as exc:
                    logging.error(
                        f"Redis operation failed while acquiring lock {mutex_key}: {exc}"
                    )
                    raise

                if acquired:
                    logging.debug(f"[Mutex Decorator] Acquired lock: {mutex_key}")
                    break

                elapsed_time = time.time() - start_time
                if elapsed_time > max_wait_time:
                    logging.error(
                        f"[Mutex Decorator] Timeout acquiring lock {mutex_key} "
                        f"(waited {elapsed_time:.2f}s > {max_wait_time:.2f}s)"
                    )
                    raise TimeOutException(
                        f"Unable to acquire lock {mutex_key} within {max_wait_time} seconds."
                    )

                await asyncio.sleep(sleep_interval)

            try:
                # Execute critical section
                return_value = await func(*args, **kwargs)
                return return_value
            finally:
                # Attempt to release the lock only if still owned by the running thread
                try:
                    current_value = await redis.get(mutex_key)
                    if current_value and current_value == mutex_value:
                        await redis.delete(mutex_key)
                        logging.debug(f"[Mutex Decorator] Released lock: {mutex_key}")
                    else:
                        logging.debug(
                            f"[Mutex Decorator] Lock {mutex_key} was already "
                            f"released or expired. Current value: {current_value}, "
                            f"Expected: {mutex_value}"
                        )
                except Exception as exc:
                    logging.error(
                        f"Redis operation failed while releasing lock {mutex_key}: {exc}"
                    )
                    raise

        return wrapper

    return decorator

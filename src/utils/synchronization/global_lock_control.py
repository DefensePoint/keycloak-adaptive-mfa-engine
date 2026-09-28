import asyncio
import time
import logging

from src.core.exception import TimeOutException
from src.core.redis import get_redis
from src.core.config.environment import CONFIG_LOCK_TIMEOUT_SECONDS

from src.utils.synchronization.dist_mutex import synchronize_with_distributed_mutex

_LOCK_PREFIX = "dist_mutex"


def _config_lock_id(resource: str, realm_id: str) -> str:
    return f"config:{resource}:{realm_id}"


def mark_config_lock(resource: str, realm_id: str):
    """Distributed mutex for a single realm's writes to a single config
    resource ("settings" or "scoring"). Scoped per realm and per resource so
    one realm's config write can never contend with another realm's, or with
    that same realm's other resource -- unlike the old single fixed
    "global_lock" key every realm's every write shared.

    `max_wait_time` is set equal to `mutex_timeout` (not left at
    synchronize_with_distributed_mutex's short default) so that a second,
    perfectly legitimate write to this SAME realm+resource waits out the
    first one's full possible hold time instead of raising a spurious
    timeout after a couple of seconds -- the lock's whole purpose is to let
    one such write run to completion while a concurrent one waits.
    """
    return synchronize_with_distributed_mutex(
        lock_id=_config_lock_id(resource, realm_id),
        prefix=_LOCK_PREFIX,
        mutex_timeout=CONFIG_LOCK_TIMEOUT_SECONDS,
        max_wait_time=CONFIG_LOCK_TIMEOUT_SECONDS,
    )


async def check_no_config_lock(
    resource: str,
    realm_id: str,
    timeout: float = CONFIG_LOCK_TIMEOUT_SECONDS,
    poll_interval: float = 0.1,
):
    """Wait for a realm's own in-flight config write (if any) to finish
    before reading that same resource, so a read right after a write sees
    consistent data. Only ever waits on this realm+resource's own key --
    never on another realm's, and never called from the decision/auth_context
    hot path (those must not block on any administrative write lock).

    Defaults to the same budget as the write lock itself
    (CONFIG_LOCK_TIMEOUT_SECONDS): a shorter default would let a perfectly
    legitimate in-flight write outlive how long this read is willing to wait
    for it, timing out on ordinary contention rather than actual overload.
    """
    redis = get_redis()
    lock_key = f"{_LOCK_PREFIX}:{_config_lock_id(resource, realm_id)}"

    start_time = time.time()

    while True:
        try:
            value = await redis.get(lock_key)
        except Exception as e:
            logging.error(f"Redis error while checking for absence of lock '{lock_key}': {e}")
            raise Exception("Redis is not functioning or unreachable.") from e

        if value is None:
            return

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            raise TimeOutException(
                f"Lock '{lock_key}' remained present for more than {timeout} seconds."
            )

        await asyncio.sleep(poll_interval)

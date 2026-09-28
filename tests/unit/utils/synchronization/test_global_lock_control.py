import pytest

from src.core.exception import TimeOutException
from src.utils.synchronization.dist_mutex import synchronize_with_distributed_mutex
from src.utils.synchronization.global_lock_control import (
    _config_lock_id,
    check_no_config_lock,
    mark_config_lock,
)


def test_lock_key_is_scoped_by_resource_and_realm():
    """Every realm+resource combination must resolve to a distinct key -- a
    single shared key is exactly what let one realm's config write stall
    every other realm's decisions."""
    assert _config_lock_id("settings", "realm-a") != _config_lock_id(
        "settings", "realm-b"
    )
    assert _config_lock_id("settings", "realm-a") != _config_lock_id(
        "scoring", "realm-a"
    )


class _FakeRedis:
    def __init__(self, value=None):
        self._value = value

    async def get(self, key):
        return self._value


@pytest.mark.asyncio(loop_scope="session")
async def test_check_no_config_lock_returns_immediately_when_key_absent(mocker):
    mocker.patch(
        "src.utils.synchronization.global_lock_control.get_redis",
        return_value=_FakeRedis(value=None),
    )
    # Must not raise and must not hang.
    await check_no_config_lock("settings", "realm-a", timeout=1.0, poll_interval=0.01)


@pytest.mark.asyncio(loop_scope="session")
async def test_check_no_config_lock_only_waits_on_its_own_realm_and_resource(mocker):
    """A lock held for realm-a's settings must never block a check for
    realm-b's settings, or for realm-a's own scoring resource."""
    seen_keys = []

    class _RecordingRedis:
        async def get(self, key):
            seen_keys.append(key)
            return None

    mocker.patch(
        "src.utils.synchronization.global_lock_control.get_redis",
        return_value=_RecordingRedis(),
    )

    await check_no_config_lock("settings", "realm-b", timeout=1.0, poll_interval=0.01)

    assert seen_keys == [f"dist_mutex:{_config_lock_id('settings', 'realm-b')}"]


@pytest.mark.asyncio(loop_scope="session")
async def test_check_no_config_lock_raises_typed_timeout_not_builtin(mocker):
    """Finding recommendation: the decision path (and any other caller) must
    get the app's own TimeOutException, handled as a proper 408, rather than
    a bare builtin TimeoutError falling through to a generic 500."""
    mocker.patch(
        "src.utils.synchronization.global_lock_control.get_redis",
        return_value=_FakeRedis(value="held"),
    )

    with pytest.raises(TimeOutException):
        await check_no_config_lock(
            "settings", "realm-a", timeout=0.05, poll_interval=0.01
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_writes_to_different_realms_do_not_contend():
    """Two realms' config writes must be able to run fully concurrently --
    the whole point of scoping the lock per realm+resource."""
    import asyncio

    order = []

    @mark_config_lock("settings", "realm-a")
    async def write_a():
        order.append("a-start")
        await asyncio.sleep(0.05)
        order.append("a-end")

    @mark_config_lock("settings", "realm-b")
    async def write_b():
        order.append("b-start")
        await asyncio.sleep(0.05)
        order.append("b-end")

    await asyncio.gather(write_a(), write_b())

    # Both should have started before either finished -- proof they ran
    # concurrently rather than serializing on a shared key.
    assert order.index("a-start") < order.index("b-end")
    assert order.index("b-start") < order.index("a-end")


@pytest.mark.asyncio(loop_scope="session")
async def test_two_writers_to_the_same_realm_and_resource_serialize_and_both_complete():
    """Two writers to the SAME
    realm+resource must serialize (the second waits for the first) rather
    than racing, AND the second must not raise a spurious timeout while
    legitimately waiting -- mark_config_lock sets max_wait_time equal to
    mutex_timeout precisely so a second, perfectly legitimate write to this
    same key waits out the first one's full possible hold time instead of
    failing after a couple of seconds. Uses synchronize_with_distributed_mutex
    directly (not mark_config_lock) with small explicit timeouts so the test
    stays fast, since the underlying serialization/wait behavior being
    proven is identical to what mark_config_lock configures."""
    import asyncio

    lock_id = _config_lock_id("settings", "realm-contend")
    order = []

    def locked(label, hold_seconds):
        @synchronize_with_distributed_mutex(
            lock_id=lock_id, mutex_timeout=1.0, max_wait_time=1.0
        )
        async def _write():
            order.append(f"{label}-start")
            await asyncio.sleep(hold_seconds)
            order.append(f"{label}-end")

        return _write()

    # Writer A holds the lock for 0.2s; writer B starts ~0.05s later and
    # must wait for A to release before its own critical section runs.
    async def delayed_b():
        await asyncio.sleep(0.05)
        await locked("b", 0.02)

    await asyncio.gather(locked("a", 0.2), delayed_b())

    # B must not even START until A has fully finished -- proof they
    # serialized on the shared key rather than one silently losing the lock
    # mid-write and letting the other in concurrently.
    assert order == ["a-start", "a-end", "b-start", "b-end"]

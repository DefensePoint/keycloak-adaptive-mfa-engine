import pytest
from datetime import datetime

from src.data.model import AuthContext
from src.data.repository import AuthContextRepository
from tests.fixture.util import unique_hash


def make_context(label: str, **overrides) -> AuthContext:
    """An auth context whose identity is unique to this run.

    A fixed hash collides with the row the previous run left behind, since these
    tests share one database and it is never reset.
    """
    fields = {
        "hash": unique_hash(label),
        "device": "Test Device",
        "client": "Test Client",
        "ip_address": "127.0.0.1",
        "system_language": "en-US",
        "screen_resolution": "1920x1080",
        "operating_system": "Linux",
        "browser": "Chrome",
        "lat": 40.7128,
        "long": -74.0060,
        "is_vpn": False,
        "country_name": "USA",
        "created_at": datetime.now(),
    }
    fields.update(overrides)
    return AuthContext(**fields)


@pytest.mark.asyncio(loop_scope="session")
async def test_create_context(tracked):
    context = make_context("test-create-context")

    created = await AuthContextRepository.create_context(context)
    tracked.add(AuthContextRepository.delete_context, created)

    assert created.hash == context.hash
    assert created.client == "Test Client"
    assert created.browser == "Chrome"
    assert created.is_vpn is False


@pytest.mark.asyncio(loop_scope="session")
async def test_get_context_by_hash(tracked):
    context = make_context(
        "test-get-context",
        device="Another Device",
        client="Another Client",
        ip_address="192.168.0.5",
        system_language="fr-FR",
        screen_resolution="1280x720",
        operating_system="Windows",
        browser="Firefox",
        lat=48.8566,
        long=2.3522,
        is_vpn=True,
        country_name="France",
    )
    await AuthContextRepository.create_context(context)
    tracked.add(AuthContextRepository.delete_context, context)

    found = await AuthContextRepository.get_context_by_hash(context.hash)

    assert found is not None
    assert found.hash == context.hash
    assert found.browser == "Firefox"
    assert found.country_name == "France"


@pytest.mark.asyncio(loop_scope="session")
async def test_list_contexts(tracked):
    for i in range(3):
        context = make_context(
            f"test-list-context-{i}",
            device=f"Device{i}",
            client="ListTestClient",
            ip_address=f"192.168.0.{10 + i}",
            system_language="en-GB",
            screen_resolution="1366x768",
            operating_system="MacOS",
            browser="Safari",
            lat=51.5074,
            long=-0.1278,
            country_name="UK",
        )
        await AuthContextRepository.create_context(context)
        tracked.add(AuthContextRepository.delete_context, context)

    all_contexts = await AuthContextRepository.list_contexts()

    limited_contexts = await AuthContextRepository.list_contexts(limit=2)

    assert len(all_contexts) >= 3
    assert len(limited_contexts) == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_update_context(tracked):
    original = make_context(
        "test-update-context",
        device="Initial Device",
        client="Initial Client",
        ip_address="10.0.0.1",
        system_language="zh-CN",
        screen_resolution="800x600",
        operating_system="Android",
        browser="Opera",
        lat=35.6895,
        long=139.6917,
        country_name="Japan",
    )
    saved = await AuthContextRepository.create_context(original)
    tracked.add(AuthContextRepository.delete_context, saved)

    saved.browser = "Opera GX"
    saved.is_vpn = True
    updated = await AuthContextRepository.update_context(saved)

    assert updated.browser == "Opera GX"
    assert updated.is_vpn is True


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_context():
    # No tracker here: deleting the row is what this test asserts.
    context_to_delete = make_context(
        "test-delete-context",
        device="DeleteTestDevice",
        client="DeleteTestClient",
        ip_address="10.10.10.10",
        system_language="es-ES",
        screen_resolution="1440x900",
        operating_system="iOS",
        browser="Chrome Mobile",
        lat=40.4168,
        long=-3.7038,
        country_name="Spain",
    )
    await AuthContextRepository.create_context(context_to_delete)

    await AuthContextRepository.delete_context(context_to_delete)

    deleted = await AuthContextRepository.get_context_by_hash(context_to_delete.hash)
    assert deleted is None

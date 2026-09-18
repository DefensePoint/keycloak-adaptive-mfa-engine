import random
import pytest
from datetime import datetime

from src.data.model.location_network import LocationNetwork
from src.data.repository.location_network import LocationNetworkRepository
from tests.fixture.util import unique_hash


def make_location_network(label: str) -> LocationNetwork:
    """A location/network row whose identity is unique to this run.

    A fixed hash collides with the row the previous run left behind, since these
    tests share one database and it is never reset.
    """
    return LocationNetwork(
        hash=unique_hash(label),
        geolocation_cluster_label=random.randint(0, 100),
        country="76",
        ip_address="192.168.0.1",
        is_vpn_flag=random.choice([0, 1]),
        created_at=datetime.now(),
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_create_location_network_context(tracked):
    location_network = make_location_network("test-create-location")

    created = await LocationNetworkRepository.create_location_network(location_network)
    tracked.add(LocationNetworkRepository.delete_location_network, created)

    assert created.hash == location_network.hash
    assert created.country == location_network.country
    assert created.ip_address == location_network.ip_address
    assert created.is_vpn_flag == location_network.is_vpn_flag


@pytest.mark.asyncio(loop_scope="session")
async def test_get_location_network_by_hash(tracked):
    location_network = make_location_network("test-get-location")

    await LocationNetworkRepository.create_location_network(location_network)
    tracked.add(LocationNetworkRepository.delete_location_network, location_network)

    found = await LocationNetworkRepository.get_location_network_by_hash(
        location_network.hash
    )

    assert found is not None
    assert found.hash == location_network.hash
    assert found.country == location_network.country
    assert found.ip_address == location_network.ip_address
    assert found.is_vpn_flag == location_network.is_vpn_flag


@pytest.mark.asyncio(loop_scope="session")
async def test_list_location_networks(tracked):
    for i in range(3):
        location_network = make_location_network(f"test-location-{i}")
        await LocationNetworkRepository.create_location_network(location_network)
        tracked.add(LocationNetworkRepository.delete_location_network, location_network)

    all_contexts = await LocationNetworkRepository.list_location_networks()

    limited_contexts = await LocationNetworkRepository.list_location_networks(limit=2)

    assert len(all_contexts) >= 3
    assert len(limited_contexts) == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_update_location_network(tracked):
    location_network = make_location_network("test-update-location")

    saved = await LocationNetworkRepository.create_location_network(location_network)
    tracked.add(LocationNetworkRepository.delete_location_network, saved)

    saved.country = "388"
    saved.is_vpn_flag = 1
    updated = await LocationNetworkRepository.update_location_network(saved)

    assert saved.country == "388"
    assert updated.is_vpn_flag == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_location_network():
    # No tracker here: deleting the row is what this test asserts.
    context_to_delete = make_location_network("test-delete-location")
    await LocationNetworkRepository.create_location_network(context_to_delete)

    await LocationNetworkRepository.delete_location_network(context_to_delete)

    deleted = await LocationNetworkRepository.get_location_network_by_hash(
        context_to_delete.hash
    )
    assert deleted is None

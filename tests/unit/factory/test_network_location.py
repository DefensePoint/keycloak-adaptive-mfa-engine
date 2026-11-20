from uuid import uuid4
import pytest
from unittest.mock import AsyncMock, MagicMock


from src.data.factory.network_location import NetworkLocationFactory
from src.data.schema import DecisionRequest
from src.utils.data_processing.user_agent import UserAgentInfo
from src.utils.data_processing.hash import hash_str


@pytest.mark.asyncio
async def test_identify_from_auth_request(mocker):
    request = MagicMock(DecisionRequest)
    request.user_id = uuid4()
    request.group_id = uuid4()
    request.realm_id = uuid4()
    request.ip_address = "192.168.1.1"
    request.client = "client"
    request.user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 5_1 like Mac OS X) AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9B179 Safari/7534.48.3"
    request.cookie = "cookie"
    request.system_language = "en"
    request.screen_resolution = "1920x1080"
    mocked_user_agent_info = UserAgentInfo(request.user_agent)
    mocked_geo_info = {
        "lat": 40.7128,
        "long": -74.0060,
        "country_name": "USA",
        "city_name": "New York",
    }
    mocked_vpn_info = {"is_vpn": True}
    mocker.patch(
        "src.data.factory.network_location.get_cached_geo_info",
        new_callable=AsyncMock,
        return_value=mocked_geo_info,
    )
    mocker.patch(
        "src.data.factory.network_location.get_cached_vpn_info",
        new_callable=AsyncMock,
        return_value=mocked_vpn_info,
    )

    attrs = [
        str(request.ip_address),
        str(mocked_vpn_info.get("is_vpn")),
        str(mocked_geo_info.get("lat")),
        str(mocked_geo_info.get("long")),
        str(mocked_geo_info.get("city_name")),
        str(mocked_geo_info.get("country_name")),
    ]

    content_str = "|".join(attrs)
    mocked_network_hash = hash_str(content_str)

    mock_ensure_network = mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.ensure_location_network",
        new_callable=AsyncMock,
        return_value="created",
    )

    network_hash = await NetworkLocationFactory.identify_from_auth_request(request)

    assert network_hash == mocked_network_hash
    mock_ensure_network.assert_awaited_once()
    assert mock_ensure_network.await_args.args[0].hash == mocked_network_hash


# --- coordinates ----------------------------------------------------------
#
# A login that fails before AMFA's step (a wrong password, an unknown user) has
# no auth_process, so location_network is the only place its coordinates can
# come from. Without them the failure cannot go on the monitoring map.


def _request(ip="198.51.100.7"):
    request = MagicMock(DecisionRequest)
    request.ip_address = ip
    return request


def _patch_lookups(mocker, geo):
    mocker.patch(
        "src.data.factory.network_location.get_cached_geo_info",
        new_callable=AsyncMock,
        return_value=geo,
    )
    mocker.patch(
        "src.data.factory.network_location.get_cached_vpn_info",
        new_callable=AsyncMock,
        return_value={"is_vpn": False},
    )
    return mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.ensure_location_network",
        new_callable=AsyncMock,
        return_value="created",
    )


ZURICH = {"lat": 47.38, "long": 8.54, "country_name": "CH", "city_name": "Zurich"}
UNRESOLVED = {"lat": 0, "long": 0, "country_name": "", "city_name": ""}


@pytest.mark.asyncio
async def test_a_network_location_is_stored_with_its_coordinates(mocker):
    """The database fills them into a row written before it had any, and
    keeps a row that has them (see the repository tests)."""
    ensure = _patch_lookups(mocker, ZURICH)
    await NetworkLocationFactory.identify_from_auth_request(_request())
    stored = ensure.await_args.args[0]
    assert (stored.lat, stored.long) == (47.38, 8.54)


@pytest.mark.asyncio
async def test_an_unresolved_address_stores_no_coordinates(mocker):
    """The lookup reports 0,0 for an address it cannot place, a private one for
    example. Stored, that would put the login in the Gulf of Guinea."""
    ensure = _patch_lookups(mocker, UNRESOLVED)
    await NetworkLocationFactory.identify_from_auth_request(_request("10.0.0.9"))
    stored = ensure.await_args.args[0]
    assert stored.lat is None and stored.long is None


@pytest.mark.asyncio
async def test_a_known_network_is_still_checked_in_the_database(mocker):
    """The database says whether a network is known, on every login, so a
    database that lost the row gets it back before anything refers to it."""
    ensure = _patch_lookups(mocker, ZURICH)
    ensure.return_value = "kept"
    first = await NetworkLocationFactory.identify_from_auth_request(_request())
    second = await NetworkLocationFactory.identify_from_auth_request(_request())
    assert first == second
    assert ensure.await_count == 2

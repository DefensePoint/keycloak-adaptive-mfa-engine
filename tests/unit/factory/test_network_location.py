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

    mock_get_network_by_hash = mocker.patch(
        "src.data.factory.network_location.get_cached_location_network_by_hash",
        new_callable=AsyncMock,
        return_value=None,
    )
    mock_create_network = mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.create_location_network",
        new_callable=AsyncMock,
        return_value=None,
    )

    device_hash = await NetworkLocationFactory.identify_from_auth_request(request)

    assert device_hash == device_hash
    mock_get_network_by_hash.assert_awaited_once_with(mocked_network_hash)
    mock_create_network.assert_awaited_once()


# --- coordinates ----------------------------------------------------------
#
# A login that fails before AMFA's step (a wrong password, an unknown user) has
# no auth_process, so location_network is the only place its coordinates can
# come from. Without them the failure cannot go on the monitoring map.


def _request(ip="198.51.100.7"):
    request = MagicMock(DecisionRequest)
    request.ip_address = ip
    return request


def _patch_lookups(mocker, geo, existing=None):
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
    mocker.patch(
        "src.data.factory.network_location.get_cached_location_network_by_hash",
        new_callable=AsyncMock,
        return_value=existing,
    )
    create = mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.create_location_network",
        new_callable=AsyncMock,
    )
    fill = mocker.patch(
        "src.data.factory.network_location.LocationNetworkRepository.set_coordinates_if_missing",
        new_callable=AsyncMock,
        return_value=True,
    )
    forget = mocker.patch(
        "src.data.factory.network_location.forget_cached_location_network",
        new_callable=AsyncMock,
    )
    return create, fill, forget


ZURICH = {"lat": 47.38, "long": 8.54, "country_name": "CH", "city_name": "Zurich"}
UNRESOLVED = {"lat": 0, "long": 0, "country_name": "", "city_name": ""}


@pytest.mark.asyncio
async def test_a_new_network_location_stores_its_coordinates(mocker):
    create, fill, _ = _patch_lookups(mocker, ZURICH)
    await NetworkLocationFactory.identify_from_auth_request(_request())
    stored = create.await_args.args[0]
    assert (stored.lat, stored.long) == (47.38, 8.54)
    fill.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unresolved_address_stores_no_coordinates(mocker):
    """The lookup reports 0,0 for an address it cannot place, a private one for
    example. Stored, that would put the login in the Gulf of Guinea."""
    create, _, _ = _patch_lookups(mocker, UNRESOLVED)
    await NetworkLocationFactory.identify_from_auth_request(_request("10.0.0.9"))
    stored = create.await_args.args[0]
    assert stored.lat is None and stored.long is None


@pytest.mark.asyncio
async def test_a_row_written_before_coordinates_existed_gets_them(mocker):
    """The row is shared by every login with the same address and location, so
    an older row keeps being reused; it gets its coordinates the next time,
    and the cached copy without them is dropped."""
    from src.data.model import LocationNetwork

    older = LocationNetwork(hash="a" * 64, ip_address="198.51.100.7", lat=None, long=None)
    create, fill, forget = _patch_lookups(mocker, ZURICH, existing=older)
    location_hash = await NetworkLocationFactory.identify_from_auth_request(_request())
    create.assert_not_awaited()
    fill.assert_awaited_once_with(location_hash, 47.38, 8.54)
    forget.assert_awaited_once_with(location_hash)


@pytest.mark.asyncio
async def test_a_row_with_coordinates_is_left_alone(mocker):
    from src.data.model import LocationNetwork

    current = LocationNetwork(hash="a" * 64, ip_address="198.51.100.7", lat=47.38, long=8.54)
    create, fill, forget = _patch_lookups(mocker, ZURICH, existing=current)
    await NetworkLocationFactory.identify_from_auth_request(_request())
    create.assert_not_awaited()
    fill.assert_not_awaited()
    forget.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unresolved_address_does_not_fill_an_older_row(mocker):
    from src.data.model import LocationNetwork

    older = LocationNetwork(hash="a" * 64, ip_address="10.0.0.9", lat=None, long=None)
    _, fill, _ = _patch_lookups(mocker, UNRESOLVED, existing=older)
    await NetworkLocationFactory.identify_from_auth_request(_request("10.0.0.9"))
    fill.assert_not_awaited()

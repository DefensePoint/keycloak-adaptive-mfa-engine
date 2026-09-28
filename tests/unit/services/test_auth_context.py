import pytest

from src.data.schema.hash_response import HashResponseSchema
from src.service.auth_context import AuthContextService
from src.data.schema.auth_context import AuthContextSchema


@pytest.mark.asyncio(loop_scope="session")
async def test_callable_auth_context(mocker):
    request = AuthContextSchema(
        client="client",
        ip_address="0.0.0.1",
        system_language="en",
        screen_resolution="1920x1080",
        user_agent="user_agent",
    )
    mocked_hash = "hash"
    mock_hash = mocker.Mock()
    mock_hash.hexdigest.return_value = mocked_hash

    mocker.patch("hashlib.sha3_256", return_value=mock_hash)
    mocker.patch("src.core.redis.get_redis", return_value=None)
    mock_device_factory = mocker.patch(
        "src.data.factory.DeviceFactory.identify_from_auth_request",
        return_value=mocked_hash,
    )
    mock_net_location_factory = mocker.patch(
        "src.data.factory.NetworkLocationFactory.identify_from_auth_request",
        return_value=mocked_hash,
    )

    _callable = AuthContextService(request)

    response = await _callable()

    assert response is not None
    assert isinstance(response, HashResponseSchema)
    assert response.hash == mocked_hash
    mock_device_factory.assert_called_with(request)
    mock_net_location_factory.assert_called_with(request)

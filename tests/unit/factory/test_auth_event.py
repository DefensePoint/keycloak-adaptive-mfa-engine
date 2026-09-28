import pytest
import json
from uuid import uuid4
from datetime import datetime

from src.data.factory.auth_event import AuthEventFactory
from src.data.model import AuthEvent
from src.data.schema import WebhookPayload
from src.utils.data_processing.hash import hash_str


@pytest.mark.asyncio
async def test_partial_from_request(mocker):

    request_id = uuid4()
    user_id = uuid4()
    event_type = "LOGIN"

    request = WebhookPayload(
        **{
            "type": "LOGIN",
            "id": str(request_id),
            "timestamp": 1,
            "data": {
                "user_id": str(user_id),
                "event_timestamp": 1,
                "auth_context_hash": "hash",
            },
            "authContextModel": {
                "client": "client",
                "ip_address": "8.8.8.8",
                "user_agent": "user_agent",
                "system_language": "en",
                "screen_resolution": "1980x1020",
            },
        }
    )

    mocked_device_hash = "device_hash"
    mocked_network_location_hash = "network_location_hash"

    mocked_auth_context_hash = "auth_context_hash"
    mock_hash = mocker.Mock()
    mock_hash.hexdigest.return_value = mocked_auth_context_hash

    mocker.patch("hashlib.sha3_256", return_value=mock_hash)

    mocker.patch(
        "src.data.factory.device.DeviceFactory.identify_from_auth_request",
        return_value=mocked_device_hash,
    )
    mocker.patch(
        "src.data.factory.network_location.NetworkLocationFactory.identify_from_auth_request",
        return_value=mocked_network_location_hash,
    )

    auth_event = await AuthEventFactory.partial_from_request(request, realm="test-amfa")

    assert auth_event.id == str(request_id)
    assert auth_event.user_id == str(user_id)
    assert auth_event.realm_id == "test-amfa"
    assert auth_event.event_type == event_type
    assert auth_event.device_info_hash == mocked_device_hash
    assert auth_event.network_location_hash == mocked_network_location_hash
    assert auth_event.auth_context_hash == mocked_auth_context_hash
    assert isinstance(auth_event.details, str)


def test_serialize():
    auth_event = AuthEvent(
        id=uuid4(),
        auth_process=uuid4(),
        user_id=uuid4(),
        event_type="LOGIN",
        details='{"some":"detail"}',
        event_time=datetime.utcnow(),
    )

    serialized = AuthEventFactory.serialize(auth_event)
    serialized_obj = json.loads(serialized)

    assert serialized_obj["id"] == str(auth_event.id)
    assert serialized_obj["auth_process"] == str(auth_event.auth_process)
    assert serialized_obj["user_id"] == str(auth_event.user_id)
    assert serialized_obj["event_type"] == auth_event.event_type
    assert serialized_obj["details"] == auth_event.details
    assert serialized_obj["event_time"] == auth_event.event_time.isoformat()


def test_deserialize():
    event_id = uuid4()
    auth_process_id = uuid4()
    user_id = uuid4()
    event_time = datetime.utcnow()

    data = json.dumps(
        {
            "id": str(event_id),
            "auth_process": str(auth_process_id),
            "user_id": str(user_id),
            "event_type": "LOGIN",
            "details": '{"some":"detail"}',
            "event_time": event_time.isoformat(),
        }
    )

    auth_event = AuthEventFactory.deserialize(data)

    assert auth_event.id == event_id
    assert auth_event.auth_process == auth_process_id
    assert auth_event.user_id == user_id
    assert auth_event.event_type == "LOGIN"
    assert auth_event.details == '{"some":"detail"}'
    assert auth_event.event_time == event_time

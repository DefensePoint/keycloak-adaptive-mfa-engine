import asyncio
from src.data.schema import WebhookPayload
from src.data.model import AuthEvent

from src.utils.data_processing.hash import hash_str

from .device import DeviceFactory
from .network_location import NetworkLocationFactory

from uuid import UUID
import json

from datetime import datetime


class AuthEventFactory:

    @staticmethod
    async def partial_from_request(request: WebhookPayload, realm: str) -> AuthEvent:
        device_hash, net_loc_hash = await asyncio.gather(
            DeviceFactory.identify_from_auth_request(request.authContextModel),
            NetworkLocationFactory.identify_from_auth_request(request.authContextModel),
        )

        _str = str(str(device_hash) + str(net_loc_hash))
        _auth_ctx_hash = hash_str(_str)

        return AuthEvent(
            id=request.id,
            user_id=request.data.user_id,
            realm_id=realm,
            event_type=request.event_type,
            details=request.data.model_dump_json(),
            auth_context_hash=_auth_ctx_hash,
            device_info_hash=device_hash,
            network_location_hash=net_loc_hash,
        )

    @staticmethod
    def serialize(auth_event: "AuthEvent") -> str:
        """Serialize an AuthEvent object into a JSON string."""
        return json.dumps(
            {
                "id": str(auth_event.id),
                "auth_process": str(auth_event.auth_process),
                "user_id": str(auth_event.user_id) if auth_event.user_id else None,
                "event_type": auth_event.event_type,
                "details": auth_event.details,
                "event_time": (auth_event.event_time.isoformat()),
            }
        )

    @staticmethod
    def deserialize(data: str) -> "AuthEvent":
        """Deserialize a JSON string back into an AuthEvent object."""
        obj = json.loads(data)
        return AuthEvent(
            id=UUID(obj["id"]),
            auth_process=UUID(obj["auth_process"]),
            user_id=UUID(obj["user_id"]) if obj["user_id"] else None,
            event_type=obj["event_type"],
            details=obj["details"],
            event_time=(
                datetime.fromisoformat(obj["event_time"]) if obj["event_time"] else None
            ),
        )

from uuid import uuid4
from datetime import datetime


from src.data.model.device import Device
from tests.fixture.util import generate_sha3_256_hash


def get_device_fixture() -> Device:
    context_hash = f"device-{uuid4()}"
    return Device(
        hash=generate_sha3_256_hash(context_hash),
        client="Client",
        device="Device",
        system_language="en",
        screen_resolution="1980x1080",
        operating_system="macOS",
        browser="Chrome",
        created_at=datetime.now(),
    )

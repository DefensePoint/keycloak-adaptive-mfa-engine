from uuid import uuid4
from datetime import datetime

import random

from src.data.model.location_network import LocationNetwork
from tests.fixture.util import generate_sha3_256_hash


def get_location_network_fixture() -> LocationNetwork:
    context_hash = f"device-{uuid4()}"
    return LocationNetwork(
        hash=generate_sha3_256_hash(context_hash),
        geolocation_cluster_label=random.randint(0, 100),
        country="76",
        ip_address="192.168.0.1",
        is_vpn_flag=random.choice([0, 1]),
        created_at=datetime.now(),
    )

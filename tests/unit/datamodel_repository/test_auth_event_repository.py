from time import sleep
from uuid import uuid4
import pytest

from datetime import datetime
from src.data.model.auth_event import AuthEvent
from src.data.repository.auth_event import AuthEventRepository
from src.data.repository.auth_process import AuthProcessRepository
from src.data.repository.location_network import LocationNetworkRepository


from src.data.repository.device import DeviceRepository
from src.data.model.auth_process import AuthProcess
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from tests.fixture.decision_params_config import get_decision_params_config_fixture
from tests.fixture.device import get_device_fixture
from tests.fixture.location_network import get_location_network_fixture


@pytest.mark.asyncio(loop_scope="session")
async def test_initial_create():
    global device
    global location_network
    global decision
    global auth_process

    device_fixture = get_device_fixture()
    location_network_fixture = get_location_network_fixture()
    decision_fixture = get_decision_params_config_fixture()
    device = await DeviceRepository.create_device(device_fixture)
    location_network = await LocationNetworkRepository.create_location_network(
        location_network_fixture
    )
    decision = await DecisionParamsConfigRepository.create_decision_params_config(
        decision_fixture
    )
    auth_process_fixture = AuthProcess(
        user_id=uuid4(),
        auth_context_hash="hash",
        device_info_hash=device.hash,
        network_location_hash=location_network.hash,
        auth_context_json={},
        pre_auth_risk_decision=1,
        parameters_config_id=decision.id,
        final_status="LOGIN",
        started_at=datetime.now(),
        device_credibility=0.3,
        net_loc_credibility=0.2,
    )
    auth_process = await AuthProcessRepository.create_auth_process(auth_process_fixture)


@pytest.mark.asyncio(loop_scope="session")
async def test_create_auth_event():
    auth_event = AuthEvent(
        auth_process=auth_process.id,
        user_id=uuid4(),
        event_type="LOGIN",
        auth_context_hash="hash",
        device_info_hash=device.hash,
        network_location_hash=location_network.hash,
        event_time=datetime.now(),
    )
    created_now = await AuthEventRepository.create_auth_event(auth_event)
    created = await AuthEventRepository.get_auth_event_by_id(event_id=created_now.id)

    assert created is not None
    assert created.user_id == auth_event.user_id
    assert created.auth_context_hash == auth_event.auth_context_hash
    assert created.device_info_hash == device.hash
    assert created.network_location_hash == location_network.hash


@pytest.mark.asyncio(loop_scope="session")
async def test_get_events_for_user_is_isolated_by_realm():
    """get_events_for_user has no current callers, but must stay realm-scoped
    so a future caller cannot be wired up unscoped by accident (see the
    Missing Tenant and Subject Binding on the Login Event Webhook finding)."""
    user_id = uuid4()
    auth_event = AuthEvent(
        user_id=user_id,
        realm_id="victim-realm",
        event_type="LOGIN",
        auth_context_hash="hash",
        device_info_hash=device.hash,
        network_location_hash=location_network.hash,
        event_time=datetime.now(),
    )
    await AuthEventRepository.create_auth_event(auth_event)

    cross_realm = await AuthEventRepository.get_events_for_user(
        user_id=user_id, realm_id="attacker-realm"
    )
    assert cross_realm == []

    same_realm = await AuthEventRepository.get_events_for_user(
        user_id=user_id, realm_id="victim-realm"
    )
    assert len(same_realm) == 1

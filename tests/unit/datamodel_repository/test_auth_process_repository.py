from uuid import uuid4
import pytest

from datetime import datetime
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


@pytest.mark.asyncio(loop_scope="session")
async def test_create_auth_process_and_get():
    auth_process = AuthProcess(
        user_id=uuid4(),
        realm_id="test-amfa",
        auth_context_hash="hash",
        device_info_hash=device.hash,
        network_location_hash=location_network.hash,
        auth_context_json={},
        pre_auth_risk_decision=1,
        parameters_config_id=decision.id,
        final_status="LOGIN",
        started_at=datetime.now(),
    )
    created_now = await AuthProcessRepository.create_auth_process(auth_process)
    created = await AuthProcessRepository.get_auth_process_by_id(
        created_now.id, realm_id="test-amfa"
    )

    assert created.user_id == auth_process.user_id
    assert created.auth_context_hash == auth_process.auth_context_hash
    assert created.device_info_hash == device.hash
    assert created.network_location_hash == location_network.hash
    assert created.parameters_config_id == decision.id


@pytest.mark.asyncio(loop_scope="session")
async def test_list_auth_processes():
    for _ in range(3):
        auth_process = AuthProcess(
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
        await AuthProcessRepository.create_auth_process(auth_process)

    all_auth_process = await AuthProcessRepository.list_auth_processes()

    limited_auth_process = await AuthProcessRepository.list_auth_processes(limit=2)

    assert len(all_auth_process) >= 3
    assert len(limited_auth_process) == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_update_auth_process():
    auth_process = AuthProcess(
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
    saved = await AuthProcessRepository.create_auth_process(auth_process)
    saved.auth_context_hash = "default"

    updated = await AuthProcessRepository.update_auth_process(saved)
    assert updated.auth_context_hash == "default"


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_auth_process():
    auth_process = AuthProcess(
        user_id=uuid4(),
        realm_id="test-amfa",
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
    saved = await AuthProcessRepository.create_auth_process(auth_process)
    await AuthProcessRepository.delete_auth_process(saved)

    deleted_auth_process = await AuthProcessRepository.get_auth_process_by_id(
        saved.id, realm_id="test-amfa"
    )
    assert deleted_auth_process is None


@pytest.mark.asyncio(loop_scope="session")
async def test_get_auth_process_by_id_is_isolated_by_realm():
    """A process id that exists but belongs to a different realm must be
    treated as not found — the finalize path (webhook LOGIN/LOGIN_ERROR)
    must never fetch or update another tenant's row even if it learns the id."""
    auth_process = AuthProcess(
        user_id=uuid4(),
        realm_id="victim-realm",
        auth_context_hash="hash",
        device_info_hash=device.hash,
        network_location_hash=location_network.hash,
        auth_context_json={},
        pre_auth_risk_decision=1,
        parameters_config_id=decision.id,
        final_status="pre-auth",
        started_at=datetime.now(),
    )
    saved = await AuthProcessRepository.create_auth_process(auth_process)

    cross_realm = await AuthProcessRepository.get_auth_process_by_id(
        saved.id, realm_id="attacker-realm"
    )
    assert cross_realm is None

    same_realm = await AuthProcessRepository.get_auth_process_by_id(
        saved.id, realm_id="victim-realm"
    )
    assert same_realm is not None
    assert same_realm.id == saved.id


@pytest.mark.asyncio(loop_scope="session")
async def test_get_complete_records_for_user():
    user_id = uuid4()
    auth_process = AuthProcess(
        user_id=user_id,
        realm_id="test-amfa",
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
    await AuthProcessRepository.create_auth_process(auth_process)
    created = await AuthProcessRepository.get_complete_records_for_user(
        user_id=user_id, realm_id="test-amfa"
    )

    assert len(created) == 1
    assert created[0].user_id == auth_process.user_id
    assert created[0].realm_id == "test-amfa"
    assert created[0].auth_context_hash == auth_process.auth_context_hash
    assert created[0].device_info_hash == device.hash
    assert created[0].network_location_hash == location_network.hash
    assert created[0].parameters_config_id == decision.id


@pytest.mark.asyncio(loop_scope="session")
async def test_get_complete_records_for_user_is_isolated_by_realm():
    """Finding #1 (Broken Access Control in the Risk Decision API): a record
    created under one realm must never be visible to a query for the same
    user_id scoped to a different realm."""
    user_id = uuid4()
    auth_process = AuthProcess(
        user_id=user_id,
        realm_id="victim-realm",
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
    await AuthProcessRepository.create_auth_process(auth_process)

    same_user_other_realm = await AuthProcessRepository.get_complete_records_for_user(
        user_id=user_id, realm_id="attacker-realm"
    )
    assert same_user_other_realm == []

    same_user_same_realm = await AuthProcessRepository.get_complete_records_for_user(
        user_id=user_id, realm_id="victim-realm"
    )
    assert len(same_user_same_realm) == 1

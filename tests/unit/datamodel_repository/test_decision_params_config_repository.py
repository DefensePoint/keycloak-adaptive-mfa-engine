import json
import random
from uuid import uuid4
import pytest
import hashlib
from datetime import datetime

from src.core.config.environment import DEFAULT_DECISION_PARAMS
from src.data.model.decision_params_config import DecisionParamsConfig
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from tests.fixture.util import generate_sha3_256_hash, unique_id


parameters = DEFAULT_DECISION_PARAMS
json_str = json.dumps(parameters, separators=(",", ":"))
sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()

delete_config = DecisionParamsConfigRepository.delete_decision_params_config

decision = DecisionParamsConfig(
    realm_id=str(uuid4()),
    group_id=str(uuid4()),
    parameters=parameters,
    parameters_hash=sha3_hash,
)


@pytest.mark.asyncio(loop_scope="session")
async def test_create_decision_params_config():
    created = await DecisionParamsConfigRepository.create_decision_params_config(
        decision
    )

    assert created.realm_id == decision.realm_id
    assert created.group_id == decision.group_id
    assert created.is_active is False
    assert created.parameters == decision.parameters
    assert created.parameters_hash == decision.parameters_hash


@pytest.mark.asyncio(loop_scope="session")
async def test_get_decision_params_config_by_id():
    created = await DecisionParamsConfigRepository.create_decision_params_config(
        decision
    )
    decision_by_id = (
        await DecisionParamsConfigRepository.get_decision_params_config_by_id(
            created.id
        )
    )
    assert decision_by_id is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_list_decision_params_configs(tracked):
    for i in range(3):
        decision = DecisionParamsConfig(
            realm_id=str(uuid4()),
            group_id=str(uuid4()),
            parameters=parameters,
            parameters_hash=sha3_hash,
        )
        await DecisionParamsConfigRepository.create_decision_params_config(decision)
        tracked.add(delete_config, decision)

    all_decisions = await DecisionParamsConfigRepository.list_decision_params_configs()

    limited_decisions = (
        await DecisionParamsConfigRepository.list_decision_params_configs(limit=2)
    )

    assert len(all_decisions) >= 3
    assert len(limited_decisions) == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_update_decision_params_config():
    saved = await DecisionParamsConfigRepository.create_decision_params_config(decision)
    saved.group_id = "default"
    saved.realm_id = "default"

    updated = await DecisionParamsConfigRepository.update_decision_params_config(saved)
    assert updated.group_id == "default"
    assert updated.realm_id == "default"


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_decision_params_config():
    decision_params = (
        await DecisionParamsConfigRepository.create_decision_params_config(decision)
    )
    await DecisionParamsConfigRepository.delete_decision_params_config(decision_params)

    deleted_decision = (
        await DecisionParamsConfigRepository.get_decision_params_config_by_id(
            decision_params.id
        )
    )
    assert deleted_decision is None


@pytest.mark.asyncio(loop_scope="session")
async def get_active_decision_params_config():
    realm_id = "realm-id-decision"
    group_id = "group-id-decision"

    activate_decision = DecisionParamsConfig(
        realm_id=realm_id,
        group_id=group_id,
        is_active=True,
        parameters=parameters,
        parameters_hash=sha3_hash,
    )
    deactivate_decision = DecisionParamsConfig(
        realm_id=realm_id,
        group_id=group_id,
        parameters=parameters,
        parameters_hash=sha3_hash,
    )
    await DecisionParamsConfigRepository.create_decision_params_config(
        activate_decision
    )
    await DecisionParamsConfigRepository.create_decision_params_config(
        deactivate_decision
    )

    decision = await DecisionParamsConfigRepository.get_active_decision_params_config(
        realm_id, group_id
    )
    assert decision is not None
    assert decision.realm_id == activate_decision.realm_id
    assert decision.group_id == activate_decision.group_id
    assert decision.is_active is True
    assert decision.parameters == activate_decision.parameters
    assert decision.parameters_hash == activate_decision.parameters_hash


@pytest.mark.asyncio(loop_scope="session")
async def test_activate_decision_params_config(tracked):
    # The realm must be unique to this run. With a fixed realm id this counted
    # every active config every previous run had left behind: the assertion below
    # was seeing 60 rather than 3.
    realm_id = unique_id("realm-id-decision-activate")
    for i in range(3):
        activate_decision = DecisionParamsConfig(
            realm_id=realm_id,
            group_id=str(uuid4()),
            is_active=True,
            parameters=parameters,
            parameters_hash=sha3_hash,
        )
        deactivate_decision = DecisionParamsConfig(
            realm_id=realm_id,
            group_id=str(uuid4()),
            parameters=parameters,
            parameters_hash=sha3_hash,
        )
        await DecisionParamsConfigRepository.create_decision_params_config(
            activate_decision
        )
        await DecisionParamsConfigRepository.create_decision_params_config(
            deactivate_decision
        )
        tracked.add(delete_config, activate_decision)
        tracked.add(delete_config, deactivate_decision)

    all_active_decision = (
        await DecisionParamsConfigRepository.get_all_active_decision_params_by_realm(
            realm_id=realm_id
        )
    )
    assert len(all_active_decision) == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_activate_decision_when_has_multiple_active_decision(tracked):
    # Unique per run for the same reason: asserting exactly one active config for
    # this realm only holds if no earlier run has already populated it.
    test_realm_id = unique_id("test_activate_decision_params_config_if_decision_exist")
    test_group_id = unique_id("test_activate_decision_params_config_if_decision_exist")

    unique_active_decision = (
        await DecisionParamsConfigRepository.activate_decision_params_config(
            realm_id=test_realm_id,
            group_id=test_group_id,
            parameters_hash=sha3_hash,
            parameters=parameters,
        )
    )
    tracked.add(delete_config, unique_active_decision)

    all_decision_by_realm = (
        await DecisionParamsConfigRepository.get_all_active_decision_params_by_realm(
            realm_id=test_realm_id
        )
    )
    assert unique_active_decision.is_active == True
    assert len(all_decision_by_realm) == 1

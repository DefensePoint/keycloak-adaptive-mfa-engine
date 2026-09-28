from unittest.mock import patch


from uuid import uuid4
from fastapi import HTTPException
import pytest

from src.core.config.environment import DEFAULT_DECISION_PARAMS
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from src.data.schema.parameter_assignment import ParameterAssignment
from src.data.model.decision_params_config import DecisionParamsConfig

from src.data.schema.parameter_assignment import ParameterAssignment
from src.service.params_config import ParamsConfigService
from tests.fixture.decision_params_config import get_decision_params_config_fixture


@pytest.mark.asyncio(loop_scope="session")
async def test_get_active_params_for_realm_group_when_active_config_is_none(mocker):
    group_id = "uuid"
    realm_id = "uuid"
    mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=None,
    )
    with pytest.raises(HTTPException) as exc:
        await ParamsConfigService.get_active_params_for_realm_group(
            realm_id=realm_id, group_id=group_id
        )

    assert isinstance(exc.value, HTTPException)
    assert exc.value.detail == (
        f"No active DecisionParamsConfig found for realm='{realm_id}' "
        f"and group='{group_id}'."
    )
    assert exc.value.status_code == 500


@pytest.mark.asyncio(loop_scope="session")
async def test_get_active_params_for_realm_group_when_active_config_parameters_not_list(
    mocker,
):
    group_id = "uuid"
    realm_id = "uuid"
    decision_mock = get_decision_params_config_fixture()
    decision_mock.parameters = None
    mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=decision_mock,
    )
    with pytest.raises(HTTPException) as exc:
        await ParamsConfigService.get_active_params_for_realm_group(
            realm_id=realm_id, group_id=group_id
        )

    assert isinstance(exc.value, HTTPException)
    assert exc.value.detail == (
        "Active DecisionParamsConfig found, but 'parameters' field "
        "is not a list as expected."
    )
    assert exc.value.status_code == 500


@pytest.mark.asyncio(loop_scope="session")
async def test_success_get_active_params_for_realm_group(
    mocker,
):
    group_id = "uuid"
    realm_id = "uuid"
    parameters = [
        {
            "group_id": "default",
            "realm_id": "default",
            "parameter_name": "client",
            "weight": 3,
            "disabled": False,
            "blacklist": None,
            "whitelist": None,
        },
    ]

    decision_mock = DecisionParamsConfig(
        realm_id=str(uuid4()),
        group_id=str(uuid4()),
        parameters=parameters,
        parameters_hash="a" * 64,
    )
    decision_mock.id = "active-uuid"
    mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=decision_mock,
    )
    response = await ParamsConfigService.get_active_params_for_realm_group(
        realm_id=realm_id, group_id=group_id
    )

    assert response is not None
    assert isinstance(response, dict)
    assert response["__meta"]["id"] == "active-uuid"

    assert response["client"]["group_id"] == "default"
    assert response["client"]["realm_id"] == "default"
    assert response["client"]["weight"] == 3
    assert response["client"]["disabled"] == False
    assert response["client"]["blacklist"] == None
    assert response["client"]["whitelist"] == None


@pytest.mark.asyncio(loop_scope="session")
async def test_update_realm_params_wrong_realm_id(mocker):
    realm_id = "uuid"
    parameter = ParameterAssignment(
        group_id="default",
        realm_id="default",
        parameter_name="client",
        weight=3,
        disabled=False,
        blacklist=None,
        whitelist=None,
    )
    parameters = [parameter]

    with pytest.raises(HTTPException) as exc_info:
        await ParamsConfigService._ParamsConfigService__update_realm_params(
            realm_id=realm_id, request=parameters
        )

    assert isinstance(exc_info.value, HTTPException)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        f"ParameterAssignment realm_id '{parameter.realm_id}' "
        f"does not match path realm_id '{realm_id}'."
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_update_realm_params(mocker):
    mock_hash = mocker.Mock()
    mock_hash.hexdigest.return_value = "mocked_hash_value"

    mocker.patch("hashlib.sha3_256", return_value=mock_hash)
    mock_repo = mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.activate_decision_params_config",
        return_value=None,
    )
    mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.get_all_active_decision_params_by_realm",
        return_value=[],
    )
    realm_id = "default"
    parameter_client = ParameterAssignment(
        group_id="default",
        realm_id="default",
        parameter_name="client",
        weight=10,
        disabled=True,
        blacklist=None,
        whitelist=None,
    )
    parameters = [parameter_client]

    await ParamsConfigService._ParamsConfigService__update_realm_params(
        realm_id=realm_id, request=parameters
    )

    updated_params = [
        {**param, "inactive_days": param.get("inactive_days")}
        for param in DEFAULT_DECISION_PARAMS
        if param["parameter_name"] != "client"
    ]
    expected_parameters = [
        {
            "group_id": "default",
            "realm_id": "default",
            "parameter_name": "client",
            "weight": 10,
            "disabled": True,
            "whitelist": None,
            "blacklist": None,
            "inactive_days": None,
        },
        *updated_params,
    ]

    assert mock_repo.call_count == 1
    mock_repo.assert_called_with(
        realm_id=realm_id,
        group_id="default",
        parameters_hash="mocked_hash_value",
        parameters=expected_parameters,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_update_realm_params_persists_submitted_inactive_days(mocker):
    """The write path must not drop a submitted inactive_days value.

    test_update_realm_params only submits a `client` row, so the
    `inactive_account` row it later inspects comes from the default back-fill,
    not from a submission — it would still pass even if the save path dropped
    a submitted inactive_days entirely. This test submits inactive_account
    directly and asserts the value survives into the parameters handed to
    activate_decision_params_config.
    """
    mock_hash = mocker.Mock()
    mock_hash.hexdigest.return_value = "mocked_hash_value"

    mocker.patch("hashlib.sha3_256", return_value=mock_hash)
    mock_repo = mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.activate_decision_params_config",
        return_value=None,
    )
    mocker.patch(
        "src.data.repository.decision_params_config.DecisionParamsConfigRepository.get_all_active_decision_params_by_realm",
        return_value=[],
    )
    realm_id = "default"
    parameter_inactive_account = ParameterAssignment(
        group_id="default",
        realm_id="default",
        parameter_name="inactive_account",
        weight=5,
        disabled=False,
        blacklist=None,
        whitelist=None,
        inactive_days=90,
    )
    parameters = [parameter_inactive_account]

    await ParamsConfigService._ParamsConfigService__update_realm_params(
        realm_id=realm_id, request=parameters
    )

    assert mock_repo.call_count == 1
    persisted_parameters = mock_repo.call_args.kwargs["parameters"]
    inactive_account_row = next(
        p for p in persisted_parameters if p["parameter_name"] == "inactive_account"
    )
    assert inactive_account_row["inactive_days"] == 90


def test_default_param_backfill_carries_inactive_days():
    """When a submission omits the inactive_account row, the default-group
    back-fill must reinstate it WITH its shipped threshold, otherwise saving an
    unrelated signal would silently blank the configured value."""
    from src.core.config.environment import (
        DEFAULT_DECISION_PARAMS,
        DEFAULT_INACTIVE_DAYS,
    )

    shipped = next(
        p
        for p in DEFAULT_DECISION_PARAMS
        if p["parameter_name"] == "inactive_account"
    )

    assert shipped["inactive_days"] == DEFAULT_INACTIVE_DAYS

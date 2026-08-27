import hashlib
import json
from fastapi import HTTPException, status
import pytest
from types import SimpleNamespace

from src.core.config.environment import DEFAULT_DECISION_PARAMS
from src.data.factory.decision_params import DecisionParamsFactory
from tests.fixture.decision_params_config import get_decision_params_config_fixture


@pytest.mark.asyncio
async def test_ensure_default_params_exist(mocker):
    mock_get_active_decision = mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=1,
    )

    mock_activate_decision = mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.activate_decision_params_config",
        return_value=None,
    )

    await DecisionParamsFactory.ensure_default_params_exist()

    assert mock_get_active_decision.call_count == 1
    mock_get_active_decision.assert_called_with(realm_id="default", group_id="default")
    assert mock_activate_decision.call_count == 0


@pytest.mark.asyncio
async def test_ensure_default_params_exist_creating_default(mocker):
    mock_get_active_decision = mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=None,
    )

    mock_activate_decision = mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.activate_decision_params_config",
        return_value=None,
    )

    await DecisionParamsFactory.ensure_default_params_exist()
    json_str = json.dumps(DEFAULT_DECISION_PARAMS, separators=(",", ":"))
    sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()

    assert mock_get_active_decision.call_count == 1
    mock_get_active_decision.assert_called_with(realm_id="default", group_id="default")
    assert mock_activate_decision.call_count == 1
    mock_activate_decision.assert_called_with(
        realm_id="default",
        group_id="default",
        parameters_hash=sha3_hash,
        parameters=DEFAULT_DECISION_PARAMS,
    )


@pytest.mark.asyncio
async def test_get_active_params_for_realm_group_raise_not_active_config(mocker):
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=None,
    )
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=None,
    )

    mock_realm_id = "id"
    mock_group_id = "id"

    with pytest.raises(ValueError) as exc:
        await DecisionParamsFactory.get_active_params_for_realm_group(
            realm_id=mock_realm_id, group_id=mock_group_id
        )

    assert (
        str(exc.value)
        == "Cannot proceed, no default configuration values in the database"
    )


@pytest.mark.asyncio
async def test_get_active_params_for_realm_group_raise_parameters_not_list(mocker):
    mock_realm_id = "id"
    mock_group_id = "id"
    mock_decision_params = get_decision_params_config_fixture()
    mock_decision_params.parameters = None
    mock_decision_repository = mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
    )
    mock_decision_repository.side_effect = [None, mock_decision_params]

    with pytest.raises(HTTPException) as exc:
        await DecisionParamsFactory.get_active_params_for_realm_group(
            realm_id=mock_realm_id, group_id=mock_group_id
        )

    assert str(exc.value.detail) == (
        "Active DecisionParamsConfig found, but 'parameters' field "
        "is not a list as expected."
    )
    assert (exc.value.status_code) == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_get_active_params_for_realm_group_raise_not_valid_params(mocker):
    mock_realm_id = "id"
    mock_group_id = "id"
    mock_decision_params = get_decision_params_config_fixture()
    mock_decision_params.parameters[0]["weight"] = ""
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=mock_decision_params,
    )

    with pytest.raises(HTTPException) as exc:
        await DecisionParamsFactory.get_active_params_for_realm_group(
            realm_id=mock_realm_id, group_id=mock_group_id
        )

    assert (exc.value.status_code) == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_get_all_parameters_by_realm(mocker):
    mock_realm_id = "id"
    mock_group_id = "id"
    mock_decision_params = get_decision_params_config_fixture()
    mock_decision_params.id = "active-uuid"
    mock_decision_params.parameters[0]["weight"] = 3
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_all_active_decision_params_by_realm",
        return_value=[mock_decision_params],
    )

    response = await DecisionParamsFactory.get_all_parameters_by_realm(
        realm=mock_realm_id
    )

    assert response is not None
    assert isinstance(response, list)

    assert response[0].group_id == "default"
    assert response[0].realm_id == "default"
    assert response[0].weight == 3
    assert response[0].disabled == True


def test_inactive_days_is_carried_into_resolved_params():
    """The resolved decision_params dict must expose the stored threshold so the
    decision pipeline can inject it into the dormancy check."""
    config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": 90,
            }
        ],
    )

    resolved = DecisionParamsFactory.format_decision_parameters_to_dict(
        group_id="default", realm_id="acme", active_config=config
    )

    assert resolved["inactive_account"]["inactive_days"] == 90


def test_inactive_days_absent_resolves_to_none():
    """A row saved before this feature has no threshold; the resolver must report
    None rather than raising, so the caller can fall back to the env default."""
    config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
            }
        ],
    )

    resolved = DecisionParamsFactory.format_decision_parameters_to_dict(
        group_id="default", realm_id="acme", active_config=config
    )

    assert resolved["inactive_account"]["inactive_days"] is None


@pytest.mark.asyncio
async def test_group_override_inherits_realm_inactive_days(mocker):
    """When a group overrides a signal, the realm-level inactive_days threshold
    must be preserved, not replaced by the override's value. A group override row
    has no inactive_days, so the resolved group config must inherit the realm's."""
    base_config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000003",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": 90,
            },
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "client",
                "weight": 2,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
            },
        ],
    )
    override_config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000004",
        scoring_config=None,
        parameters=[
            {
                "group_id": "g1",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 5,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
            },
        ],
    )

    def mock_get_config(realm_id, group_id):
        if group_id == "default":
            return base_config
        elif group_id == "g1":
            return override_config
        return None

    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        side_effect=mock_get_config,
    )

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id="acme", group_id="g1"
    )

    assert resolved["inactive_account"]["weight"] == 5
    assert resolved["inactive_account"]["inactive_days"] == 90


@pytest.mark.asyncio
async def test_group_override_cannot_set_its_own_inactive_days(mocker):
    """When a group override row carries its own inactive_days value, it must be
    ignored and replaced with the realm's threshold. The inactive_days field is
    realm-level only and cannot vary by group."""
    base_config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000005",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": 90,
            },
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "client",
                "weight": 2,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
            },
        ],
    )
    override_config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000006",
        scoring_config=None,
        parameters=[
            {
                "group_id": "g1",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 5,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": 5,
            },
        ],
    )

    def mock_get_config(realm_id, group_id):
        if group_id == "default":
            return base_config
        elif group_id == "g1":
            return override_config
        return None

    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        side_effect=mock_get_config,
    )

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id="acme", group_id="g1"
    )

    assert resolved["inactive_account"]["weight"] == 5
    assert resolved["inactive_account"]["inactive_days"] == 90


def test_fill_effective_inactive_days_backfills_unset_rows():
    """A row saved before the feature existed must report the EFFECTIVE threshold
    on read, so the admin console shows the number actually being enforced
    instead of a blank box."""
    from src.core.config.environment import DEFAULT_INACTIVE_DAYS

    params = [
        {"parameter_name": "inactive_account", "weight": 3, "disabled": False},
        {"parameter_name": "country_name", "weight": 3, "disabled": False},
    ]

    filled = DecisionParamsFactory._fill_effective_inactive_days(params)

    assert filled[0]["inactive_days"] == DEFAULT_INACTIVE_DAYS
    # Unrelated signals must not gain the key.
    assert "inactive_days" not in filled[1]


def test_fill_effective_inactive_days_preserves_a_configured_value():
    params = [
        {
            "parameter_name": "inactive_account",
            "weight": 3,
            "disabled": False,
            "inactive_days": 90,
        }
    ]

    filled = DecisionParamsFactory._fill_effective_inactive_days(params)

    assert filled[0]["inactive_days"] == 90


@pytest.mark.asyncio
async def test_decision_path_normalizes_stored_boolean_inactive_days(mocker):
    """A stored `True` (e.g. hand-edited or written by a non-admin-UI client)
    must not survive pydantic's int|None coercion (True -> 1) into a one-day
    dormancy threshold on the decision path. get_active_params_for_realm_group
    must normalize the RAW dict before it reaches ParameterAssignment."""
    from src.core.config.environment import DEFAULT_INACTIVE_DAYS

    config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000010",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": True,
            },
        ],
    )
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=config,
    )

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id="acme", group_id="default"
    )

    assert resolved["inactive_account"]["inactive_days"] == DEFAULT_INACTIVE_DAYS


@pytest.mark.asyncio
async def test_decision_path_normalizes_stored_string_inactive_days(mocker):
    """A stored numeric string (e.g. `"90"`) would otherwise be coerced by
    pydantic to the int 90 before resolve_inactive_threshold's non-int guard
    can ever see it, making the engine enforce 90 days while the admin console
    (which goes through the RAW-dict back-fill) still reports the default.
    Normalizing the RAW dict up front keeps both paths in agreement."""
    from src.core.config.environment import DEFAULT_INACTIVE_DAYS

    config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000011",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": "90",
            },
        ],
    )
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=config,
    )

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id="acme", group_id="default"
    )

    assert resolved["inactive_account"]["inactive_days"] == DEFAULT_INACTIVE_DAYS


@pytest.mark.asyncio
async def test_decision_path_normalizes_stored_zero_inactive_days(mocker):
    """A stored `0` means "unset" everywhere (zero would flag every login as
    dormant), so the decision path must resolve it to the deployment default,
    not a one-day threshold."""
    from src.core.config.environment import DEFAULT_INACTIVE_DAYS

    config = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000012",
        scoring_config=None,
        parameters=[
            {
                "group_id": "default",
                "realm_id": "acme",
                "parameter_name": "inactive_account",
                "weight": 3,
                "disabled": False,
                "whitelist": None,
                "blacklist": None,
                "inactive_days": 0,
            },
        ],
    )
    mocker.patch(
        "src.data.repository.DecisionParamsConfigRepository.get_active_decision_params_config",
        return_value=config,
    )

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id="acme", group_id="default"
    )

    assert resolved["inactive_account"]["inactive_days"] == DEFAULT_INACTIVE_DAYS


def test_fill_effective_inactive_days_replaces_a_nonsense_value():
    """Zero would flag every login as dormant, so it is treated as unset."""
    from src.core.config.environment import DEFAULT_INACTIVE_DAYS

    params = [
        {
            "parameter_name": "inactive_account",
            "weight": 3,
            "disabled": False,
            "inactive_days": 0,
        }
    ]

    filled = DecisionParamsFactory._fill_effective_inactive_days(params)

    assert filled[0]["inactive_days"] == DEFAULT_INACTIVE_DAYS

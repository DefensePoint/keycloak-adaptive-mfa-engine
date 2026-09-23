import pytest
from fastapi import HTTPException

import src.api.decision_route as decision_route_mod
import src.api.params_route as params_route_mod
from src.api.decision_route import DecisionRoute
from src.api.params_route import ParamsRoute
from src.data.schema import DecisionRequest
from src.utils.auth.token_verifier import VerifiedPrincipal


def _principal(realm):
    return VerifiedPrincipal(issuer=f"https://kc/realms/{realm}", realm=realm,
                             client_id="c", roles=[], audiences=["amfa"],
                             subject="u", claims={})


def _decision_request(realm_id):
    return DecisionRequest(
        event_id="e", group_id="g", realm_id=realm_id, user_id="u",
        client="c", ip_address="1.1.1.1", user_agent="ua",
        system_language="en", screen_resolution="1x1",
        auth_context_hash="h",
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_decision_rejects_cross_tenant():
    route = DecisionRoute()
    with pytest.raises(HTTPException) as e:
        await route.decision_post(_decision_request("realm-b"), principal=_principal("realm-a"))
    assert e.value.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_decision_evaluation_error_surfaces_instead_of_fabricating_a_verdict(
    monkeypatch,
):
    """A failure inside DecisionService must propagate (so the registered
    exception handlers turn it into a non-2xx response with no riskLevel
    body) rather than being swallowed into a fake, permissive HTTP 200. The
    pending auth_process Redis marker must still be cleared on the way out.
    """

    class _BoomService:
        def __init__(self, request):
            pass

        async def __call__(self):
            raise RuntimeError("boom")

    deleted_keys = []

    class _FakeRedis:
        async def delete(self, key):
            deleted_keys.append(key)

    async def _no_rate_limit(realm_id, user_id):
        return None

    monkeypatch.setattr(decision_route_mod, "DecisionService", _BoomService)
    monkeypatch.setattr(decision_route_mod, "control_rate_limit", _no_rate_limit)
    monkeypatch.setattr(decision_route_mod, "get_redis", lambda: _FakeRedis())

    route = DecisionRoute()
    with pytest.raises(RuntimeError):
        await route.decision_post(
            _decision_request("realm-a"), principal=_principal("realm-a")
        )

    assert deleted_keys == ["auth_process:realm-a:u"]


@pytest.mark.asyncio(loop_scope="session")
async def test_params_get_rejects_cross_tenant():
    route = ParamsRoute()
    with pytest.raises(HTTPException) as e:
        await route.process_get_settings_request("realm-b", principal=_principal("realm-a"))
    assert e.value.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_params_put_rejects_cross_tenant():
    route = ParamsRoute()
    with pytest.raises(HTTPException) as e:
        await route.process_put_settings_request("realm-b", request=[], principal=_principal("realm-a"))
    assert e.value.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_params_put_rejects_oversized_group_count():
    """Each distinct group_id in the submission is one write inside the realm's
    config-write lock, so an unbounded count let a request's own body size
    dictate how long that lock (and, before the fix, every OTHER realm's
    decisions too) was stalled. Must be rejected before the lock or the DB
    are ever touched."""
    from src.core.config.environment import MAX_CONFIG_GROUPS_PER_REQUEST
    from src.data.schema import ParameterAssignment

    too_many_groups = [
        ParameterAssignment(
            group_id=f"group-{i}",
            realm_id="realm-a",
            parameter_name="client",
            weight=1,
            disabled=False,
            blacklist=None,
            whitelist=None,
        )
        for i in range(MAX_CONFIG_GROUPS_PER_REQUEST + 1)
    ]

    route = ParamsRoute()
    with pytest.raises(HTTPException) as e:
        await route.process_put_settings_request(
            "realm-a", request=too_many_groups, principal=_principal("realm-a")
        )
    assert e.value.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_params_put_accepts_group_count_at_the_boundary(monkeypatch):
    """The cap must reject only what's OVER the limit -- exactly the maximum
    allowed group count must still be accepted."""
    from src.core.config.environment import MAX_CONFIG_GROUPS_PER_REQUEST
    from src.data.schema import ParameterAssignment

    exactly_at_cap = [
        ParameterAssignment(
            group_id=f"group-{i}",
            realm_id="realm-a",
            parameter_name="client",
            weight=1,
            disabled=False,
            blacklist=None,
            whitelist=None,
        )
        for i in range(MAX_CONFIG_GROUPS_PER_REQUEST)
    ]

    async def _no_rate_limit(realm_id, user_id, bucket="decision"):
        return None

    async def _no_lock(resource, realm_id):
        return None

    async def _no_op_update(realm_id, request):
        return None

    monkeypatch.setattr(params_route_mod, "control_rate_limit", _no_rate_limit)
    monkeypatch.setattr(params_route_mod, "check_no_config_lock", _no_lock)
    monkeypatch.setattr(
        params_route_mod.ParamsConfigService, "update_realm_params", _no_op_update
    )

    route = ParamsRoute()
    result = await route.process_put_settings_request(
        "realm-a", request=exactly_at_cap, principal=_principal("realm-a")
    )
    assert result == "success"

"""Hermetic e2e for signal gating: real Postgres + Redis, no Keycloak.

Complements the live ``run_e2e.py`` suite. Where ``run_e2e.py`` drives the full
Keycloak + engine + MFA wiring over HTTP, this pytest module exercises the
gating machinery the fix touches directly against real datastores, so it runs
in the ``pytest ./tests`` sweep without a running Keycloak:

  Part A (Postgres): a realm config is persisted and activated, then resolved
  through the REAL DecisionParamsFactory.get_active_params_for_realm_group
  (which strips disabled signals). A DecisionService reading that config must
  gate recent_account_change / login_failure / concurrent_session correctly.

  Part B (Redis): sensitive account-action events are written under the same
  cache keys the ingestion path uses (d:<EVENT_TYPE>:<user>:<epoch>), and the
  REAL __count_recent_account_actions scans them, honouring the time window.

This is the hermetic counterpart to run_e2e.py's ``sc_disabled_signal_does_not_fire``
and ``sc_e4_account_change``. Requires migrations applied and REDIS/POSTGRES env
pointing at live datastores.
"""

import hashlib
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.redis import get_redis
from src.data.factory import DecisionParamsFactory
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from src.service.decision import DecisionService
from src.service.risk_evaluation.checks import process_account_action

GATED_SIGNALS = ["recent_account_change", "login_failure", "concurrent_session"]


def _params(realm_id: str, disabled: bool) -> list:
    """A realm parameter set: one always-on anchor signal plus the three signals
    the fix regates, all disabled or all enabled per `disabled`."""

    def entry(name: str, is_disabled: bool) -> dict:
        return {
            "group_id": "default",
            "realm_id": realm_id,
            "parameter_name": name,
            "weight": 3,
            "disabled": is_disabled,
            "blacklist": None,
            "whitelist": None,
        }

    params = [entry("impossible_travel", False)]  # anchor: always enabled
    params += [entry(name, disabled) for name in GATED_SIGNALS]
    return params


async def _seed_and_load(disabled: bool) -> dict:
    """Persist+activate a realm config, then resolve it through the real factory."""
    realm_id = str(uuid4())
    params = _params(realm_id, disabled=disabled)
    params_hash = hashlib.sha3_256(
        json.dumps(params, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    await DecisionParamsConfigRepository.activate_decision_params_config(
        realm_id=realm_id,
        group_id="default",
        parameters_hash=params_hash,
        parameters=params,
    )
    return await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id, "default"
    )


def _svc(decision_params: dict) -> DecisionService:
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = decision_params
    return svc


# --- Part A: DB config -> resolved decision_params -> gating -----------------


@pytest.mark.asyncio(loop_scope="session")
async def test_disabled_signals_are_stripped_and_gated_off():
    resolved = await _seed_and_load(disabled=True)
    svc = _svc(resolved)

    # Disabled signals are stripped from the resolved config...
    for name in GATED_SIGNALS:
        assert name not in resolved, f"{name} should be stripped when disabled"
        assert svc._DecisionService__param_is_enabled(name) is False

    # ...while an enabled anchor signal survives and reads as enabled.
    assert "impossible_travel" in resolved
    assert svc._DecisionService__param_is_enabled("impossible_travel") is True


@pytest.mark.asyncio(loop_scope="session")
async def test_enabled_signals_are_present_and_gated_on():
    resolved = await _seed_and_load(disabled=False)
    svc = _svc(resolved)

    for name in GATED_SIGNALS:
        assert name in resolved, f"{name} should be present when enabled"
        assert svc._DecisionService__param_is_enabled(name) is True
        assert resolved[name]["weight"] == 3  # per-realm weight preserved


# --- Part B: real Redis account-action scan ----------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_count_recent_account_actions_honours_window_via_real_redis():
    redis = get_redis()
    realm_id = str(uuid4())
    user_id = str(uuid4())
    now = time.time()

    # A recent password change (in window) and a stale one (3 days ago, out of
    # the default 24h window), written exactly as the ingestion path writes them
    # -- tenant-scoped (realm_id:user_id), per tenant_scoped_id(), not user_id
    # alone. Every per-user Redis key is realm-scoped this way; this stub had
    # fallen out of sync with that and needed updating to match.
    recent_key = f"d:UPDATE_PASSWORD:{realm_id}:{user_id}:{now}"
    stale_key = f"d:UPDATE_PASSWORD:{realm_id}:{user_id}:{now - 3 * 86400}"
    await redis.set(recent_key, now, ex=86400)
    await redis.set(stale_key, now, ex=86400)

    svc = DecisionService.__new__(DecisionService)
    svc.redis = redis
    svc.request_payload = SimpleNamespace(realm_id=realm_id, user_id=user_id)

    count = await svc._DecisionService__count_recent_account_actions()

    assert count == 1, f"only the in-window change should count, got {count}"
    assert process_account_action(count) == "SUSPICIOUS"
    assert process_account_action(0) == "NORMAL"


@pytest.mark.asyncio(loop_scope="session")
async def test_no_recent_account_actions_is_normal_via_real_redis():
    redis = get_redis()
    realm_id = str(uuid4())
    user_id = str(uuid4())  # no keys seeded for this user

    svc = DecisionService.__new__(DecisionService)
    svc.redis = redis
    svc.request_payload = SimpleNamespace(realm_id=realm_id, user_id=user_id)

    count = await svc._DecisionService__count_recent_account_actions()

    assert count == 0
    assert process_account_action(count) == "NORMAL"

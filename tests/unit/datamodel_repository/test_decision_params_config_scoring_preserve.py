"""Regression tests for fix/preserve-scoring-config.

scoring_config (mode/bias/thresholds) is managed via a separate endpoint and
stored on the active DecisionParamsConfig row. Activating a parameter config
(a parameter edit) must carry the CURRENTLY-ACTIVE scoring_config onto the
new/reactivated row verbatim — including None — so a parameter change never
disturbs the realm's scoring settings.

DB-backed: point POSTGRES_* at a migrated database (the docker test/compose
stack provides one).
"""

import hashlib
import json
from uuid import uuid4

import pytest

from src.data.repository.decision_params_config import DecisionParamsConfigRepository as Repo

GROUP = "default"


def _params(tag: str):
    p = [{
        "group_id": GROUP, "realm_id": "r", "parameter_name": tag,
        "weight": 3, "disabled": True, "blacklist": None, "whitelist": None,
    }]
    h = hashlib.sha3_256(json.dumps(p, separators=(",", ":")).encode()).hexdigest()
    return p, h


async def _activate(realm, params, h):
    return await Repo.activate_decision_params_config(
        realm_id=realm, group_id=GROUP, parameters_hash=h, parameters=params
    )


async def _active_scoring(realm):
    c = await Repo.get_active_decision_params_config(realm, GROUP)
    return c.scoring_config if c else "NO_ACTIVE"


@pytest.mark.asyncio(loop_scope="session")
async def test_param_update_preserves_set_scoring_config():
    """Editing parameters keeps a previously-set scoring_config (the fix)."""
    realm = str(uuid4())
    p1, h1 = _params("p1")
    p2, h2 = _params("p2")
    scoring = {"mode": "bayesian", "bias": -4.2, "thresholds": [0.2, 0.55, 0.9]}

    await _activate(realm, p1, h1)
    await Repo.update_scoring_config(realm, GROUP, scoring)
    await _activate(realm, p2, h2)  # parameter edit -> new active config row

    assert await _active_scoring(realm) == scoring


@pytest.mark.asyncio(loop_scope="session")
async def test_param_revert_does_not_resurrect_stale_scoring():
    """Edge the `if preserved is not None` guard missed: when current scoring is
    None, reactivating a previously-active parameter hash must NOT bring back
    that old row's stale scoring_config."""
    realm = str(uuid4())
    p1, h1 = _params("p1")
    p2, h2 = _params("p2")

    await _activate(realm, p1, h1)
    await Repo.update_scoring_config(realm, GROUP, {"mode": "bayesian"})  # A gets scoring
    await _activate(realm, p2, h2)                    # C created, carries scoring
    await Repo.update_scoring_config(realm, GROUP, None)  # current scoring cleared to None
    await _activate(realm, p1, h1)                    # reactivate A (existing hash)

    # Current active scoring was None, so the reactivated row must be None too,
    # NOT A's stale {"mode": "bayesian"}.
    assert await _active_scoring(realm) is None

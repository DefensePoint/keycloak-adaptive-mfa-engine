"""Hermetic e2e for the realm-level dormancy threshold.

Persists a realm config carrying `inactive_days`, resolves it through the REAL
DecisionParamsFactory, and asserts the dormancy check honours the configured
value rather than the deployment default. Also asserts the read path reports an
effective value for a config saved WITHOUT the field, which is the pre-feature
shape every existing realm has.

Requires migrations applied and POSTGRES env pointing at a live database
(Dockerfile.test provides one).
"""

import datetime
import hashlib
import json
import time
from uuid import uuid4

import pandas as pd
import pytest

from src.core.config.environment import DEFAULT_INACTIVE_DAYS
from src.data.factory import DecisionParamsFactory
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from src.service.risk_evaluation.checks.inactive_account import (
    process_inactive_account,
    resolve_inactive_threshold,
)


def _ts(dt: datetime.datetime) -> float:
    return time.mktime(dt.timetuple()) * 1e3 + dt.microsecond / 1e3


def _params(realm_id: str, inactive_days: int | None) -> list:
    """A minimal realm parameter set with inactive_account enabled."""
    row = {
        "group_id": "default",
        "realm_id": realm_id,
        "parameter_name": "inactive_account",
        "weight": 3,
        "disabled": False,
        "whitelist": None,
        "blacklist": None,
    }
    if inactive_days is not None:
        row["inactive_days"] = inactive_days
    return [row]


async def _activate(realm_id: str, params: list) -> None:
    json_str = json.dumps(params, separators=(",", ":"))
    await DecisionParamsConfigRepository.activate_decision_params_config(
        realm_id=realm_id,
        group_id="default",
        parameters_hash=hashlib.sha3_256(json_str.encode("utf-8")).hexdigest(),
        parameters=params,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_configured_threshold_survives_persistence_and_is_enforced():
    realm_id = f"e2e-inactive-{uuid4().hex[:8]}"
    await _activate(realm_id, _params(realm_id, 90))

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id, "default"
    )
    assert resolved["inactive_account"]["inactive_days"] == 90

    # A 41-day gap: dormant under the 40-day default, active under this realm's 90.
    stored = pd.DataFrame({"event_time": [_ts(datetime.datetime(2024, 5, 21))]})
    current = {"event_time": _ts(datetime.datetime(2024, 7, 1))}

    threshold = resolve_inactive_threshold(
        resolved["inactive_account"]["inactive_days"]
    )
    assert process_inactive_account(stored, current, threshold) == "ACTIVE"
    assert process_inactive_account(stored, current, DEFAULT_INACTIVE_DAYS) == "INACTIVE"


@pytest.mark.asyncio(loop_scope="session")
async def test_preexisting_config_without_the_field_falls_back():
    """The shape every realm configured before this feature has: no `inactive_days`
    in the stored parameters. Proves the decision path normalizes that gap to the
    deployment default, and that the resulting threshold is the one actually
    enforced for this realm, by driving `process_inactive_account` with gaps
    derived from `DEFAULT_INACTIVE_DAYS` on both sides of it."""
    realm_id = f"e2e-inactive-legacy-{uuid4().hex[:8]}"
    await _activate(realm_id, _params(realm_id, None))

    resolved = await DecisionParamsFactory.get_active_params_for_realm_group(
        realm_id, "default"
    )
    assert resolved["inactive_account"]["inactive_days"] == DEFAULT_INACTIVE_DAYS

    threshold = resolve_inactive_threshold(
        resolved["inactive_account"]["inactive_days"]
    )
    assert threshold == DEFAULT_INACTIVE_DAYS

    current = {"event_time": _ts(datetime.datetime(2024, 7, 1))}

    # A gap one day beyond the default: dormant under this realm's effective threshold.
    stored_beyond = pd.DataFrame(
        {
            "event_time": [
                _ts(
                    datetime.datetime(2024, 7, 1)
                    - datetime.timedelta(days=DEFAULT_INACTIVE_DAYS + 1)
                )
            ]
        }
    )
    assert process_inactive_account(stored_beyond, current, threshold) == "INACTIVE"

    # A gap one day inside the default: still active under this realm's effective threshold.
    stored_inside = pd.DataFrame(
        {
            "event_time": [
                _ts(
                    datetime.datetime(2024, 7, 1)
                    - datetime.timedelta(days=DEFAULT_INACTIVE_DAYS - 1)
                )
            ]
        }
    )
    assert process_inactive_account(stored_inside, current, threshold) == "ACTIVE"


@pytest.mark.asyncio(loop_scope="session")
async def test_get_settings_reports_an_effective_threshold():
    """The console must never render a blank box for a signal that is enforcing
    a real number."""
    realm_id = f"e2e-inactive-effective-{uuid4().hex[:8]}"
    await _activate(realm_id, _params(realm_id, None))

    all_params = await DecisionParamsFactory.get_all_parameters_by_realm(realm_id)
    row = next(p for p in all_params if p.parameter_name == "inactive_account")

    assert row.inactive_days == DEFAULT_INACTIVE_DAYS

from src.data.model.decision_params_config import DecisionParamsConfig
from src.data.schema import ParameterAssignment
from typing import List
from types import SimpleNamespace

from src.data.repository import DecisionParamsConfigRepository
from pydantic import TypeAdapter, ValidationError

from src.core.config.environment import DEFAULT_DECISION_PARAMS, DEFAULT_INACTIVE_DAYS

import logging

from src.data.schema import ParameterAssignment
from src.data.repository import DecisionParamsConfigRepository

from typing import List

from pydantic import ValidationError
from fastapi import HTTPException, status

from src.core.config.environment import DEFAULT_DECISION_PARAMS
from typing import Any, Dict
import json
import hashlib


class DecisionParamsFactory:

    @staticmethod
    def _seed_missing_defaults(
        params: List[dict], realm_id: str, group_id: str = "default"
    ) -> List[dict]:
        """Back-fill any DEFAULT_DECISION_PARAMS signals missing from a saved config.

        Makes the parameter set forward-compatible: when a new signal is added to
        DEFAULT_DECISION_PARAMS, it automatically appears in every realm's config
        at read time instead of requiring a data migration (and instead of the old
        behaviour of rejecting configs whose parameter count no longer matched).

        Missing signals are seeded with their shipped defaults (which are
        ``disabled=True``), so upgrading an existing deployment never silently
        changes its scoring — an operator still opts the new signal in per realm.
        Saved entries are preserved as-is; new signals are appended at the end.
        """
        present = {p["parameter_name"] for p in params}
        result = list(params)
        for default_param in DEFAULT_DECISION_PARAMS:
            if default_param["parameter_name"] not in present:
                seeded = dict(default_param)
                seeded["realm_id"] = realm_id
                seeded["group_id"] = group_id
                result.append(seeded)
        return result

    @staticmethod
    def _fill_effective_inactive_days(params: List[dict]) -> List[dict]:
        """Report the dormancy threshold the engine will actually enforce.

        A config saved before `inactive_days` existed carries no value, and a
        hand-edited one may carry a nonsense value. Either way the engine falls
        back to DEFAULT_INACTIVE_DAYS at decision time, so the read path reports
        that same number. Otherwise the admin console would render an empty box
        for a signal that is demonstrably enforcing 40 days, which is the
        confusion this feature exists to remove.

        Only the `inactive_account` row is touched. Rows are copied, not mutated.
        """
        result = []
        for param in params:
            if param.get("parameter_name") != "inactive_account":
                result.append(param)
                continue

            filled = dict(param)
            configured = filled.get("inactive_days")
            if not isinstance(configured, int) or isinstance(configured, bool) or configured < 1:
                filled["inactive_days"] = DEFAULT_INACTIVE_DAYS
            result.append(filled)
        return result

    @staticmethod
    async def get_all_parameters_by_realm(realm: str) -> List[ParameterAssignment]:
        configs = await DecisionParamsConfigRepository.get_all_active_decision_params_by_realm(
            realm_id=realm
        )

        all_parameters: List[ParameterAssignment] = []

        if not configs:
            for param in DEFAULT_DECISION_PARAMS:
                try:
                    parameter = ParameterAssignment(**param)
                    # Update the realm_id for the default parameter.
                    parameter.realm_id = realm
                    all_parameters.append(parameter)
                except Exception as e:
                    print(f"Error processing default parameter {param}: {e}")
                    raise (e)

        else:
            type_adapter = TypeAdapter(List[ParameterAssignment])

            for config in configs:
                if config.parameters is None:
                    continue
                params = config.parameters
                # The default group must expose the full signal set. Rather than
                # rejecting a config whose parameter count no longer matches the
                # defaults (which broke every time a signal was added), back-fill
                # any missing default signals so the set is forward-compatible.
                # Non-default groups are intentional sparse overrides and are left
                # untouched.
                if config.group_id == "default":
                    params = DecisionParamsFactory._seed_missing_defaults(
                        params, realm_id=realm, group_id="default"
                    )
                    params = DecisionParamsFactory._fill_effective_inactive_days(
                        params
                    )
                try:
                    parameters = type_adapter.validate_python(params)
                    all_parameters.extend(parameters)
                except Exception as e:
                    raise ValueError(
                        f"Error parsing parameters for config ID {config.id}: {e}"
                    )

        return all_parameters

    @staticmethod
    async def get_active_params_for_realm_group(
        realm_id: str, group_id: str = "default"
    ) -> Dict[str, Dict[str, Any]]:

        group_config = (
            await DecisionParamsConfigRepository.get_active_decision_params_config(
                realm_id=realm_id, group_id=group_id
            )
        )

        # The realm default group is the complete base set. A non-default group
        # is a sparse set of per-signal overrides; signals it does not specify
        # inherit the realm default. Resolve the base, then overlay overrides.
        if group_id == "default":
            base_config = group_config
            override_config = None
        else:
            base_config = (
                await DecisionParamsConfigRepository.get_active_decision_params_config(
                    realm_id=realm_id, group_id="default"
                )
            )
            override_config = group_config

        if base_config is None:
            logging.warning(
                "No active config for realm='%s' group='%s'; falling back to "
                "the global default/default configuration.",
                realm_id,
                group_id,
            )
            base_config = (
                await DecisionParamsConfigRepository.get_active_decision_params_config(
                    realm_id="default", group_id="default"
                )
            )

        if base_config is None:
            raise ValueError(
                "Cannot proceed, no default configuration values in the database"
            )

        if not isinstance(base_config.parameters, list):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Active DecisionParamsConfig found, but 'parameters' field "
                    "is not a list as expected."
                ),
            )

        # Merge raw params (which retain disabled flags) by parameter_name:
        # the override entry, when present, replaces the base entry.
        merged_by_name: Dict[str, Any] = {
            p["parameter_name"]: p for p in base_config.parameters
        }
        # Forward-compatibility: back-fill any default signals the saved base
        # config is missing (e.g. a signal added after this realm was last
        # configured), so new signals are evaluated without a manual migration.
        # Seeded as their shipped default (disabled), so an upgrade never
        # silently changes an existing realm's scoring.
        for default_param in DEFAULT_DECISION_PARAMS:
            name = default_param["parameter_name"]
            if name not in merged_by_name:
                seeded = dict(default_param)
                seeded["realm_id"] = realm_id
                merged_by_name[name] = seeded

        # Extract base inactive_days before overlay so we can preserve it.
        # inactive_days is realm-level only and must not be overridden by group configs.
        base_inactive_days = None
        if "inactive_account" in merged_by_name:
            base_inactive_days = merged_by_name["inactive_account"].get("inactive_days")

        if override_config and isinstance(override_config.parameters, list):
            for p in override_config.parameters:
                merged_by_name[p["parameter_name"]] = p

        # Restore the realm-level inactive_days threshold: group overrides must not
        # change this value, which applies realm-wide. Copy the entry before modifying
        # to avoid mutating the DB object.
        if "inactive_account" in merged_by_name:
            inactive_account_entry = dict(merged_by_name["inactive_account"])
            inactive_account_entry["inactive_days"] = base_inactive_days
            merged_by_name["inactive_account"] = inactive_account_entry

        # Normalize the RAW merged inactive_days before it is handed to
        # format_decision_parameters_to_dict, which validates through
        # ParameterAssignment (pydantic). Pydantic coerces an int|None field
        # (e.g. True -> 1, "90" -> 90, 90.0 -> 90) or raises (e.g. 90.5) before
        # resolve_inactive_threshold ever sees the value, so that resolver's
        # guards are unreachable on this path. Normalizing here keeps this path
        # in agreement with the read-path back-fill in get_all_parameters_by_realm.
        #
        # This MUST run AFTER the realm-level force directly above, not before:
        # the force sets inactive_days to base_inactive_days (the realm
        # default-group's raw, possibly-bad value) regardless of what a group
        # override supplied, so normalizing beforehand would normalize a value
        # that then gets overwritten by the still-unnormalized base value.
        # Running after ensures the final, forced value is the one normalized.
        merged_by_name = {
            p["parameter_name"]: p
            for p in DecisionParamsFactory._fill_effective_inactive_days(
                list(merged_by_name.values())
            )
        }

        meta_config = override_config or base_config
        merged_config = SimpleNamespace(
            id=meta_config.id,
            parameters=list(merged_by_name.values()),
            scoring_config=getattr(base_config, "scoring_config", None),
        )

        formatted_response = DecisionParamsFactory.format_decision_parameters_to_dict(
            group_id=group_id, realm_id=realm_id, active_config=merged_config
        )

        return formatted_response

    @staticmethod
    def format_decision_parameters_to_dict(
        group_id: str, realm_id: str, active_config: DecisionParamsConfig
    ) -> dict:
        valid_params: List[ParameterAssignment] = []
        for item in active_config.parameters:
            try:
                # This can be removed, but forces data validation
                # Good for incomplete DB migrations
                param = ParameterAssignment(**item)
                if not param.disabled:
                    valid_params.append(param)
            except ValidationError as exc:
                logging.error(
                    f"Invalid parameter data in config (realm='{realm_id}', "
                    f"group='{group_id}'): {exc}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                )

        params_dict: Dict[str, Dict[str, Any]] = {}
        for param in valid_params:
            params_dict[param.parameter_name] = {
                "group_id": param.group_id,
                "realm_id": param.realm_id,
                "weight": param.weight,
                "disabled": param.disabled,
                "blacklist": param.blacklist,
                "whitelist": param.whitelist,
                "inactive_days": param.inactive_days,
            }

        params_dict["__meta"] = {
            "id": str(active_config.id),
            "scoring_config": getattr(active_config, "scoring_config", None),
        }

        return params_dict

    @staticmethod
    async def ensure_default_params_exist():
        """
        Checks if an active config for realm_id='default' and group_id='default' exists.
        If none is found, calls ParamsConfigService to create the default set of parameters.
        """
        logging.info(
            "Ensuring default realm=default, group=default parameters exist..."
        )

        existing_config = (
            await DecisionParamsConfigRepository.get_active_decision_params_config(
                realm_id="default", group_id="default"
            )
        )
        if existing_config:
            logging.info("Default–default parameters already exist. Skipping creation.")
            return

        json_str = json.dumps(DEFAULT_DECISION_PARAMS, separators=(",", ":"))
        sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()

        await DecisionParamsConfigRepository.activate_decision_params_config(
            realm_id="default",
            group_id="default",
            parameters_hash=sha3_hash,
            parameters=DEFAULT_DECISION_PARAMS,
        )
        logging.debug(
            f"Activated params config realm='default' group='default' "
            f"with hash={sha3_hash} and params={DEFAULT_DECISION_PARAMS}"
        )

        logging.info("Default–default configuration created successfully.")

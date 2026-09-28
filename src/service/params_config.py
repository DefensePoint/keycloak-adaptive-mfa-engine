import logging

from src.data.factory.decision_params import DecisionParamsFactory
from src.utils.synchronization.global_lock_control import mark_config_lock
from src.data.schema import ParameterAssignment
from src.data.repository import DecisionParamsConfigRepository

from typing import List
from collections import defaultdict

from fastapi import HTTPException, status

from src.core.config.environment import DEFAULT_DECISION_PARAMS
from typing import Any, Dict

import json
import hashlib


class ParamsConfigService:
    @staticmethod
    async def update_realm_params(realm_id: str, request: List[ParameterAssignment]):
        @mark_config_lock("settings", realm_id)
        async def __safe_call():
            return await ParamsConfigService.__update_realm_params(realm_id, request)

        result = await __safe_call()
        return result

    @staticmethod
    async def __update_realm_params(realm_id: str, request: List[ParameterAssignment]):
        logging.info("Locked function is doing critical work...")

        for param in request:
            if param.realm_id != realm_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"ParameterAssignment realm_id '{param.realm_id}' "
                        f"does not match path realm_id '{realm_id}'."
                    ),
                )

        grouped_parameters = defaultdict(list)
        for param in request:
            # Normalize empty/missing group to "default" so an unset group
            # (e.g. an override row with no group selected) folds into the
            # default config instead of creating a phantom active config that
            # would shadow the real one on read.
            group_id = param.group_id or "default"
            param.group_id = group_id
            grouped_parameters[group_id].append(param)

        # Deactivate any previously active non-default group whose overrides
        # were all removed in this submission, so stale group configs don't
        # keep shadowing signals on read.
        submitted_groups = set(grouped_parameters.keys())
        existing_active = (
            await DecisionParamsConfigRepository.get_all_active_decision_params_by_realm(
                realm_id=realm_id
            )
        )
        for cfg in existing_active:
            cfg_group = cfg.group_id or "default"
            if cfg_group != "default" and cfg_group not in submitted_groups:
                await DecisionParamsConfigRepository.deactivate_group_config(
                    realm_id=realm_id, group_id=cfg_group
                )

        for group_id, params_list in grouped_parameters.items():
            existing_param_names = {p.parameter_name for p in params_list}

            # Only the default group holds a complete parameter set; it is the
            # base every request falls back to. Non-default groups are sparse
            # overrides — they store only the signals the admin customized for
            # that group, and unspecified signals inherit the default group at
            # decision time. So we only backfill/size-check the default group.
            if group_id == "default":
                for default_param in DEFAULT_DECISION_PARAMS:
                    if default_param["parameter_name"] not in existing_param_names:
                        fallback_assignment = ParameterAssignment(
                            group_id=group_id,
                            realm_id=realm_id,
                            parameter_name=default_param["parameter_name"],
                            weight=default_param["weight"],
                            disabled=default_param["disabled"],
                            whitelist=None,
                            blacklist=None,
                            inactive_days=default_param.get("inactive_days"),
                        )
                        params_list.append(fallback_assignment)

            # !TODO validate params black and white lists with validator functions
            params_dict_list = [p.dict() for p in params_list]

            if (
                group_id == "default"
                and len(params_dict_list) != len(DEFAULT_DECISION_PARAMS)
            ):
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Expected {len(DEFAULT_DECISION_PARAMS)} parameters for the "
                        f"default group but got {len(params_dict_list)}."
                    ),
                )

            # A non-default group with no overrides left is dropped rather than
            # stored as an empty config.
            if group_id != "default" and not params_dict_list:
                continue

            json_str = json.dumps(params_dict_list, separators=(",", ":"))
            sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()

            await DecisionParamsConfigRepository.activate_decision_params_config(
                realm_id=realm_id,
                group_id=group_id,
                parameters_hash=sha3_hash,
                parameters=params_dict_list,
            )
            logging.debug(
                f"Activated params config realm - {realm_id} group - {group_id} with {params_dict_list}, with hash {sha3_hash}"
            )

    @staticmethod
    async def get_scoring_config(
        realm_id: str, group_id: str = "default"
    ) -> Dict[str, Any] | None:
        active_config = (
            await DecisionParamsConfigRepository.get_active_decision_params_config(
                realm_id=realm_id, group_id=group_id
            )
        )
        if not active_config:
            return None
        return active_config.scoring_config

    @staticmethod
    async def update_scoring_config(
        realm_id: str, scoring_config: Dict[str, Any], group_id: str = "default"
    ):
        @mark_config_lock("scoring", realm_id)
        async def __safe_call():
            result = await DecisionParamsConfigRepository.update_scoring_config(
                realm_id=realm_id, group_id=group_id, scoring_config=scoring_config
            )
            if result is None:
                # No active params config yet (scoring saved before any risk
                # parameters). Seed the default parameter set so the scoring
                # config has an active row to attach to, then retry.
                json_str = json.dumps(DEFAULT_DECISION_PARAMS, separators=(",", ":"))
                sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()
                await DecisionParamsConfigRepository.activate_decision_params_config(
                    realm_id=realm_id,
                    group_id=group_id,
                    parameters_hash=sha3_hash,
                    parameters=DEFAULT_DECISION_PARAMS,
                )
                result = await DecisionParamsConfigRepository.update_scoring_config(
                    realm_id=realm_id, group_id=group_id, scoring_config=scoring_config
                )
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        f"Failed to persist scoring config for realm='{realm_id}' "
                        f"group='{group_id}'."
                    ),
                )
            return result

        return await __safe_call()

    @staticmethod
    async def get_active_params_for_realm_group(
        realm_id: str, group_id: str
    ) -> Dict[str, Dict[str, Any]]:
        active_config = (
            await DecisionParamsConfigRepository.get_active_decision_params_config(
                realm_id=realm_id, group_id=group_id
            )
        )
        if not active_config:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"No active DecisionParamsConfig found for realm='{realm_id}' "
                    f"and group='{group_id}'."
                ),
            )

        if not isinstance(active_config.parameters, list):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Active DecisionParamsConfig found, but 'parameters' field "
                    "is not a list as expected."
                ),
            )

        formatted_response = DecisionParamsFactory.format_decision_parameters_to_dict(
            group_id=group_id, realm_id=realm_id, active_config=active_config
        )

        return formatted_response

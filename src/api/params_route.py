from fastapi import APIRouter, Depends, HTTPException

from src.data.schema import ParameterAssignment, ScoringConfig
from src.data.factory import DecisionParamsFactory
from src.service import ParamsConfigService


from src.utils.auth.dependency import require_auth, enforce_tenant
from src.utils.auth.token_verifier import VerifiedPrincipal
from src.utils.synchronization import check_no_config_lock
from src.utils.middleware.rate_limit import control_rate_limit
from src.core.config.environment import MAX_CONFIG_GROUPS_PER_REQUEST

from typing import List, Optional


class ParamsRoute:
    def __init__(self):
        self.router = APIRouter()

        self.router.add_api_route(
            "/{realm_id}/settings",
            self.process_get_settings_request,
            methods=["GET"],
            dependencies=[Depends(require_auth)],
        )
        self.router.add_api_route(
            "/{realm_id}/settings",
            self.process_put_settings_request,
            methods=["PUT"],
            dependencies=[Depends(require_auth)],
        )
        self.router.add_api_route(
            "/{realm_id}/scoring",
            self.process_get_scoring_request,
            methods=["GET"],
            dependencies=[Depends(require_auth)],
        )
        self.router.add_api_route(
            "/{realm_id}/scoring",
            self.process_put_scoring_request,
            methods=["PUT"],
            dependencies=[Depends(require_auth)],
        )

    async def process_get_settings_request(
        self,
        realm_id: str,
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> List[ParameterAssignment]:
        enforce_tenant(principal, realm_id)
        await check_no_config_lock("settings", realm_id)

        return await DecisionParamsFactory.get_all_parameters_by_realm(realm_id)

    async def process_put_settings_request(
        self,
        realm_id: str,
        request: List[ParameterAssignment],
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> str:
        enforce_tenant(principal, realm_id)

        # Reject oversized submissions before ever touching the lock or the
        # DB: each distinct group_id is one write inside the realm's
        # config-write lock, so an unbounded count lets a request's body size
        # dictate how long that lock is held.
        submitted_groups = {p.group_id or "default" for p in request}
        if len(submitted_groups) > MAX_CONFIG_GROUPS_PER_REQUEST:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Request submits {len(submitted_groups)} distinct groups, "
                    f"which exceeds the maximum of {MAX_CONFIG_GROUPS_PER_REQUEST} "
                    "allowed per request. Split the submission into multiple requests."
                ),
            )

        await control_rate_limit(
            realm_id=realm_id,
            user_id=principal.client_id or principal.subject,
            bucket="config",
        )
        await check_no_config_lock("settings", realm_id)

        await ParamsConfigService.update_realm_params(realm_id, request)
        return "success"

    async def process_get_scoring_request(
        self,
        realm_id: str,
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> Optional[ScoringConfig]:
        enforce_tenant(principal, realm_id)
        await check_no_config_lock("scoring", realm_id)

        config = await ParamsConfigService.get_scoring_config(realm_id)
        return ScoringConfig(**config) if config else None

    async def process_put_scoring_request(
        self,
        realm_id: str,
        request: ScoringConfig,
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> str:
        enforce_tenant(principal, realm_id)
        await control_rate_limit(
            realm_id=realm_id,
            user_id=principal.client_id or principal.subject,
            bucket="config",
        )
        await check_no_config_lock("scoring", realm_id)

        await ParamsConfigService.update_scoring_config(realm_id, request.model_dump())
        return "success"

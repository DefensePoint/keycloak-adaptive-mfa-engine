import logging
from fastapi import APIRouter, Depends

from src.service import DecisionService
from src.utils.middleware.rate_limit import control_rate_limit

from src.service import AuthContextService

from src.data.schema import (
    DecisionRequest,
    DecisionResponse,
    AuthContextSchema,
    HashResponseSchema,
)

from src.utils.auth.dependency import require_auth, enforce_tenant, tenant_scoped_id
from src.utils.auth.token_verifier import VerifiedPrincipal

from src.core.redis import get_redis


class DecisionRoute:
    def __init__(self):
        self.router = APIRouter()
        self.router.add_api_route(
            "/decision",
            self.decision_post,
            methods=["POST"],
            dependencies=[Depends(require_auth)],
        )
        self.router.add_api_route(
            "/auth_context",
            self.auth_context,
            methods=["POST"],
            dependencies=[Depends(require_auth)],
        )

    async def decision_post(
        self,
        request: DecisionRequest,
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> DecisionResponse:
        enforce_tenant(principal, request.realm_id)
        await control_rate_limit(realm_id=request.realm_id, user_id=request.user_id)

        logging.debug(f"Risk level decision request {request.model_dump_json()}")

        _eval_risk = DecisionService(request)

        try:
            return await _eval_risk()
        except Exception:
            # Fail closed: an evaluation error must never be answered with a
            # verdict (a scored response tells Keycloak's conditional subflow
            # whether to demand a second factor, so a fabricated "successful"
            # low-risk answer removes the step-up exactly when something has
            # gone wrong). Clear the pending auth_process marker so a retried
            # request starts clean, then let the failure surface as a real
            # error. The registered exception handlers (exception_handler.py)
            # turn this into a non-2xx response with no riskLevel in the
            # body — Keycloak's own client already treats any non-2xx from
            # this endpoint as a failure and applies its own configured
            # fallback rather than trusting a body that was never sent.
            logging.exception(
                "Risk decision evaluation failed for user_id=%s realm_id=%s",
                request.user_id,
                request.realm_id,
            )
            redis = get_redis()
            await redis.delete(
                f"auth_process:{tenant_scoped_id(request.realm_id, request.user_id)}"
            )
            raise

    async def auth_context(
        self,
        request: AuthContextSchema,
        principal: VerifiedPrincipal = Depends(require_auth),
    ) -> HashResponseSchema:
        _callable = AuthContextService(request)

        return await _callable()

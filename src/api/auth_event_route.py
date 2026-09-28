from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import ValidationError

from src.data.schema import WebhookPayload
from src.service import AuthEventService
from src.utils.auth.dependency import require_webhook_auth, enforce_webhook_subject
from src.utils.auth.token_verifier import VerifiedPrincipal


class AuthEventRoute:
    def __init__(self):
        self.router = APIRouter()
        self.router.add_api_route(
            "/login_event/webhook",
            self.auth_event_post,
            methods=["POST"],
        )

    async def auth_event_post(
        self,
        request: Request,
        principal: VerifiedPrincipal = Depends(require_webhook_auth),
    ):
        # The event fields sit at the top level of the verified token claims
        # (alongside the registered iss/iat/exp/jti/aud, which the schema ignores).
        # Build the payload from the SIGNED claims, never the raw request body.
        try:
            payload = WebhookPayload.model_validate(principal.claims)
        except ValidationError:
            raise HTTPException(
                status_code=400, detail="Signed payload is not a valid auth event"
            )

        # The token's own subject must match the user the event claims to be
        # about, or a token issued for one identity could report an event
        # about a different one (see: Missing Tenant and Subject Binding on
        # the Login Event Webhook).
        enforce_webhook_subject(principal, payload.data.user_id)

        # realm comes from the verified token issuer (principal.realm), never
        # from the payload — the payload's own fields are attacker-shapeable
        # claim content and must not be trusted as the tenant boundary.
        service = AuthEventService(payload, realm=principal.realm)
        return await service()

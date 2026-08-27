import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.auth_event_route import AuthEventRoute
import src.api.auth_event_route as route_mod
from src.utils.auth.dependency import require_webhook_auth


def _request(headers: dict) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "state": {}})


class _Principal:
    def __init__(self, claims, realm="r", subject="u1"):
        self.claims = claims
        self.realm = realm
        self.subject = subject


@pytest.mark.asyncio(loop_scope="session")
async def test_webhook_dependency_rejects_missing_token():
    # real require_webhook_auth -> verify_signed_payload raises 401 before any network call
    with pytest.raises(HTTPException) as e:
        await require_webhook_auth(_request({}))
    assert e.value.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_webhook_handler_processes_event_from_claim(monkeypatch):
    captured = {}

    class _Service:
        def __init__(self, payload, realm):
            captured["payload"] = payload
            captured["realm"] = realm

        async def __call__(self):
            return None

    monkeypatch.setattr(route_mod, "AuthEventService", _Service)

    # Backward-compatible layout: event fields at the TOP LEVEL of the verified
    # claims, alongside the registered claims (which the schema ignores).
    principal = _Principal({
        "iss": "https://kc/realms/r", "iat": 1, "exp": 9999999999, "jti": "j1", "aud": "amfa",
        "type": "LOGIN", "id": "e1", "timestamp": 1,
        "data": {"user_id": "u1", "event_timestamp": 1, "auth_context_hash": "h"},
        "authContextModel": {"client": "c", "ip_address": "1.1.1.1",
                             "user_agent": "ua", "system_language": "en",
                             "screen_resolution": "1x1"}})

    route = AuthEventRoute()
    await route.auth_event_post(_request({}), principal=principal)
    assert captured["payload"].data.user_id == "u1"
    # The tenant boundary must come from the verified principal, never from
    # anything inside the (attacker-shapeable) claims/payload content.
    assert captured["realm"] == "r"


@pytest.mark.asyncio(loop_scope="session")
async def test_webhook_rejects_subject_mismatch():
    # A token issued to one identity (principal.subject) must not be able to
    # report an event about a different identity (data.user_id), even when
    # the signing realm is legitimate.
    principal = _Principal(
        {
            "iss": "https://kc/realms/r", "iat": 1, "exp": 9999999999, "jti": "j2",
            "aud": "amfa-webhook-event",
            "type": "LOGIN", "id": "e2", "timestamp": 1,
            "data": {"user_id": "victim", "event_timestamp": 1, "auth_context_hash": "h"},
            "authContextModel": {"client": "c", "ip_address": "1.1.1.1",
                                 "user_agent": "ua", "system_language": "en",
                                 "screen_resolution": "1x1"},
        },
        subject="attacker",
    )

    route = AuthEventRoute()
    with pytest.raises(HTTPException) as e:
        await route.auth_event_post(_request({}), principal=principal)
    assert e.value.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_webhook_rejects_token_without_event_fields():
    # A validly-signed token that is NOT an event (e.g. a plain service-account token,
    # only registered claims) must be rejected -> cannot inject a fake auth event.
    principal = _Principal({"iss": "https://kc/realms/r", "exp": 9999999999,
                            "jti": "j1", "aud": "amfa"})
    route = AuthEventRoute()
    with pytest.raises(HTTPException) as e:
        await route.auth_event_post(_request({}), principal=principal)
    assert e.value.status_code == 400

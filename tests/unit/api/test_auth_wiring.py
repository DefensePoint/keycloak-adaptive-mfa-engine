"""DI-level auth wiring tests.

Unlike test_route_auth.py / test_webhook_auth.py (which call handlers directly and
bypass FastAPI's dependency injection), these drive the real ASGI app in-process so
the router-level `require_auth` / `require_webhook_auth` dependencies actually run.
This guards against the F2-class regression: a protected route silently losing its
auth dependency would be caught here.

A tiny stdlib ASGI driver is used instead of FastAPI's TestClient so no new
dependency (httpx) is required.
"""
import pytest
from fastapi import FastAPI, Depends

from src.api.decision_route import DecisionRoute
from src.api.params_route import ParamsRoute
from src.api.auth_event_route import AuthEventRoute
from src.api.health_route import HealthRoute
from src.utils.auth.dependency import require_auth, require_webhook_auth
import src.utils.auth.dependency as dep
from src.utils.auth.token_verifier import VerifiedPrincipal


async def _asgi(app, method, path, headers=None, body=b""):
    """Send one HTTP request through the ASGI app; return (status, body bytes)."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": raw_headers, "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 12345),
    }
    sent = {"done": False}
    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}
    out = {"status": None, "body": b""}
    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")
    await app(scope, receive, send)
    return out["status"], out["body"]


def _app():
    """Mirror server_init.py's router wiring exactly (protected-by-default)."""
    app = FastAPI()
    app.include_router(DecisionRoute().router, dependencies=[Depends(require_auth)])
    app.include_router(ParamsRoute().router, dependencies=[Depends(require_auth)])
    app.include_router(AuthEventRoute().router, dependencies=[Depends(require_webhook_auth)])
    app.include_router(HealthRoute().router)
    return app


@pytest.mark.asyncio(loop_scope="session")
async def test_decision_requires_auth_through_stack():
    status, _ = await _asgi(_app(), "POST", "/decision", body=b"{}")
    assert status == 401  # require_auth rejects before the handler / body validation

@pytest.mark.asyncio(loop_scope="session")
async def test_params_requires_auth_through_stack():
    status, _ = await _asgi(_app(), "GET", "/somerealm/settings")
    assert status == 401

@pytest.mark.asyncio(loop_scope="session")
async def test_webhook_requires_auth_through_stack():
    status, _ = await _asgi(_app(), "POST", "/login_event/webhook", body=b"{}")
    assert status == 401  # require_webhook_auth rejects (no SignedPayload)

@pytest.mark.asyncio(loop_scope="session")
async def test_health_is_open_not_auth_gated():
    status, _ = await _asgi(_app(), "GET", "/health")
    assert status != 401  # open route: 200 (deps up) or 503 (deps down), never 401

@pytest.mark.asyncio(loop_scope="session")
async def test_health_detail_requires_auth_through_stack():
    """Unlike plain /health above, the full diagnostic inventory (absolute
    filesystem paths, database ages, loaded-category labels) must never be
    reachable without a credential -- confirmed the same way DecisionRoute/
    ParamsRoute are, through the real ASGI stack rather than a direct handler call."""
    status, _ = await _asgi(_app(), "GET", "/health/detail")
    assert status == 401

@pytest.mark.asyncio(loop_scope="session")
async def test_health_detail_authenticated_request_returns_full_detail(monkeypatch):
    """Companion to test_health_detail_requires_auth_through_stack: proves the
    gate actually opens for a valid token, through the real ASGI stack (not a
    direct handler call, which bypasses require_auth entirely and would not
    catch a regression where the dependency silently stopped being enforced
    but the handler still worked)."""
    monkeypatch.setattr(
        dep, "verify_token",
        lambda token: VerifiedPrincipal(
            issuer="i", realm="r", client_id="c", roles=[], audiences=["amfa"],
            subject="s", claims={},
        ),
    )
    status, body = await _asgi(
        _app(), "GET", "/health/detail", headers={"Authorization": "Bearer x"},
    )
    assert status in (200, 503)  # past auth; whichever readiness state applies
    assert b"ip_data" in body

@pytest.mark.asyncio(loop_scope="session")
async def test_authenticated_request_passes_dependency(monkeypatch):
    # With a valid principal, the dependency lets the request through to the endpoint;
    # empty body then fails validation (422) -> proves auth PASSED, not blocked at 401.
    monkeypatch.setattr(
        dep, "verify_token",
        lambda token: VerifiedPrincipal(
            issuer="i", realm="r", client_id="c", roles=[], audiences=["amfa"],
            subject="s", claims={},
        ),
    )
    status, _ = await _asgi(
        _app(), "POST", "/decision",
        headers={"Authorization": "Bearer x"}, body=b"{}",
    )
    assert status == 422  # past auth; DecisionRequest body validation fails on {}

"""Tenant and subject binding on the login event webhook.

Without a dedicated audience check, the webhook would accept any token
signed by any realm hosted on the trusted Keycloak instance, and applying
the event to whatever user identifier appears inside the signed payload,
with no check that the signing realm owns that user or that the token's
subject relates to it in any way, would let an ordinary service-account
token from an unrelated realm -- reshaped into the expected event structure
via Keycloak protocol mappers -- write an authentication event attributed
to a victim in a different realm.

The webhook requires a dedicated audience (`AMFA_WEBHOOK_AUDIENCE`) and that
the token's own subject match the event's claimed `data.user_id`. These
tests provision a throwaway realm (via `MatrixRun`) and reshape its own
`adaptive-auth-api` client's tokens -- via the same Keycloak protocol-mapper
technique used to demonstrate the original attack -- to exercise the webhook
exactly as an attacker holding realm-admin rights over their own tenant
would, never as a higher-privileged actor.

Runs from the host against a live stack; needs `requests` and Docker
(MatrixRun creates/destroys the throwaway realm, and the helpers here reshape
its own client's protocol mappers directly via the Keycloak Admin API).
"""

import json
import time
import uuid

import pytest
import requests

from tests.e2e import e2e_common as c
from tests.e2e import matrix_env as env

TIMEOUT = 20
CLIENT_ID = "adaptive-auth-api"


def _client_uuid(admin_tok: str, realm: str, client_id: str) -> str:
    r = requests.get(
        f"{env.KC_BASE}/admin/realms/{realm}/clients",
        headers={"Authorization": f"Bearer {admin_tok}"},
        params={"clientId": client_id},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()[0]["id"]


def _clear_shaping_mappers(admin_tok: str, realm: str, client_uuid: str) -> None:
    """Remove any webhook-shaping mappers left by a previous reshape in this
    run, so successive tests in this module can give the same client a
    different shape without colliding on mapper names."""
    r = requests.get(
        f"{env.KC_BASE}/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models",
        headers={"Authorization": f"Bearer {admin_tok}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    for mapper in r.json():
        if mapper["name"].startswith("wh-"):
            requests.delete(
                f"{env.KC_BASE}/admin/realms/{realm}/clients/{client_uuid}"
                f"/protocol-mappers/models/{mapper['id']}",
                headers={"Authorization": f"Bearer {admin_tok}"},
                timeout=TIMEOUT,
            ).raise_for_status()


def _add_hardcoded_claim(
    admin_tok: str,
    realm: str,
    client_uuid: str,
    name: str,
    claim_name: str,
    value,
    json_type: str = "String",
) -> None:
    r = requests.post(
        f"{env.KC_BASE}/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models",
        headers={"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"},
        data=json.dumps(
            {
                "name": name,
                "protocol": "openid-connect",
                "protocolMapper": "oidc-hardcoded-claim-mapper",
                "config": {
                    "claim.name": claim_name,
                    "claim.value": value if isinstance(value, str) else json.dumps(value),
                    "jsonType.label": json_type,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                    "userinfo.token.claim": "false",
                },
            }
        ),
        timeout=TIMEOUT,
    )
    r.raise_for_status()


def _webhook_shaped_token(
    realm: str,
    *,
    aud: str | None,
    sub: str | None,
    user_id: str,
    ip_address: str = "203.0.113.5",
) -> tuple[str, str]:
    """Reshape the realm's own adaptive-auth-api client to mint a token shaped
    like a login-event webhook payload: ordinary Keycloak hardcoded-claim
    protocol mappers on a client the realm admin already controls, not any
    special engine or webhook access -- the same technique used to
    demonstrate the original attack.

    Returns (token, event_id).
    """
    admin_tok = env.admin_token()
    client_uuid = _client_uuid(admin_tok, realm, CLIENT_ID)
    _clear_shaping_mappers(admin_tok, realm, client_uuid)

    event_id = str(uuid.uuid4())
    ts = int(time.time())

    if aud is not None:
        _add_hardcoded_claim(admin_tok, realm, client_uuid, "wh-aud", "aud", aud)
    _add_hardcoded_claim(admin_tok, realm, client_uuid, "wh-type", "type", "LOGIN")
    _add_hardcoded_claim(admin_tok, realm, client_uuid, "wh-id", "id", event_id)
    _add_hardcoded_claim(
        admin_tok, realm, client_uuid, "wh-timestamp", "timestamp", str(ts), "long"
    )
    _add_hardcoded_claim(
        admin_tok,
        realm,
        client_uuid,
        "wh-data",
        "data",
        {"user_id": user_id, "event_timestamp": ts, "auth_context_hash": "e2e-hash"},
        "JSON",
    )
    _add_hardcoded_claim(
        admin_tok,
        realm,
        client_uuid,
        "wh-authctx",
        "authContextModel",
        {
            "client": "e2e-client",
            "ip_address": ip_address,
            "user_agent": "e2e-ua",
            "system_language": "en-US",
            "screen_resolution": "1920x1080",
        },
        "JSON",
    )
    if sub is not None:
        _add_hardcoded_claim(admin_tok, realm, client_uuid, "wh-sub", "sub", sub)

    token = env.engine_token(realm)
    return token, event_id


def _post_webhook(signed_payload: str) -> requests.Response:
    return requests.post(
        f"{c.ENGINE_BASE}/login_event/webhook",
        headers={"SignedPayload": signed_payload},
        json={},
        timeout=TIMEOUT,
    )


def _create_isolated_realm() -> str:
    """Like `matrix_env.create_run_realm`, but pins `frontendUrl` to the
    engine's trusted issuer base instead of leaving it unset, and skips
    matrix parameter/scoring setup (not needed for these tests).

    `create_run_realm` deliberately strips `frontendUrl` so a realm's tokens
    claim whatever hostname actually issued them -- fine when the suite runs
    somewhere that hostname is already what the engine trusts. This suite
    runs from the host against `localhost:8443`, which is NOT what the
    engine trusts (`https://keycloak:8443`); the shipped `test-amfa` realm
    pins the same attribute for the same reason (see docs/keycloak-setup.md).
    """
    realm_name = f"amfa-e2e-webhook-{uuid.uuid4().hex[:8]}"
    admin_tok = env.admin_token()
    rep = env._realm_representation(realm_name)
    rep.setdefault("attributes", {})["frontendUrl"] = "https://keycloak:8443"
    r = requests.post(
        f"{env.KC_BASE}/admin/realms",
        headers={"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"},
        data=json.dumps(rep),
        timeout=90,
    )
    if r.status_code not in (201, 204):
        raise RuntimeError(f"could not create realm {realm_name!r} ({r.status_code}): {r.text[:400]}")
    return realm_name


@pytest.fixture(scope="module")
def other_realm():
    """A throwaway realm the "attacker" fully administers -- no more
    privilege than an ordinary realm admin over their own tenant."""
    realm_name = _create_isolated_realm()
    try:
        yield realm_name
    finally:
        env.delete_run_realm(realm_name)


@pytest.fixture
def created_events():
    """Event ids written directly by these tests via the webhook, which
    MatrixRun's own teardown cannot find (it only removes auth_event rows
    linked to a tracked auth_process id, and these forged events have none)."""
    ids = []
    yield ids
    for event_id in ids:
        env.psql(f"delete from auth_event where id = '{event_id}';")


def test_webhook_rejects_a_token_without_the_dedicated_audience(other_realm):
    """A token from a legitimate (if unrelated) realm, shaped like an event,
    but without the webhook's dedicated audience, must be rejected before
    its content is ever trusted."""
    victim_user = str(uuid.uuid4())
    token, _ = _webhook_shaped_token(other_realm, aud=None, sub=None, user_id=victim_user)

    resp = _post_webhook(token)
    assert resp.status_code == 403, resp.text[:300]


def test_webhook_rejects_subject_mismatch(other_realm):
    """Correct audience, but the token's own subject (its real
    service-account identity) does not match the claimed data.user_id --
    must be rejected even though the signing realm is legitimate."""
    victim_user = str(uuid.uuid4())
    token, _ = _webhook_shaped_token(
        other_realm, aud="amfa-webhook-event", sub=None, user_id=victim_user
    )

    resp = _post_webhook(token)
    assert resp.status_code == 403, resp.text[:300]


def test_a_fully_forged_event_is_still_contained_to_its_own_realm(
    other_realm, created_events
):
    """The disclosed residual risk: a realm admin CAN forge `sub` to match
    `data.user_id` (Keycloak allows overriding `sub` via a hardcoded-claim
    mapper on a client they control), so a fully self-consistent forged
    event is accepted -- but it must still be recorded under the SIGNING
    realm, never test-amfa's, so it can never poison another tenant's real
    training history."""
    victim_user = str(uuid.uuid4())
    token, event_id = _webhook_shaped_token(
        other_realm, aud="amfa-webhook-event", sub=victim_user, user_id=victim_user
    )
    created_events.append(event_id)

    resp = _post_webhook(token)
    assert resp.status_code == 200, resp.text[:300]

    realm_id = env.psql(f"select realm_id from auth_event where id = '{event_id}';")
    assert realm_id == other_realm, (
        f"a forged event was recorded under realm_id={realm_id!r}, expected it to "
        f"be contained to the signing realm {other_realm!r} instead"
    )


def test_webhook_accepts_a_genuinely_self_consistent_event(other_realm, created_events):
    """The happy path must still work: a token whose own subject genuinely
    matches the claimed user_id, with the correct audience, is accepted and
    recorded -- the fix must narrow the failure mode, not break normal use."""
    real_user = str(uuid.uuid4())
    token, event_id = _webhook_shaped_token(
        other_realm, aud="amfa-webhook-event", sub=real_user, user_id=real_user
    )
    created_events.append(event_id)

    resp = _post_webhook(token)
    assert resp.status_code == 200, resp.text[:300]

    stored_user = env.psql(f"select user_id from auth_event where id = '{event_id}';")
    assert stored_user == real_user

"""Exercises the REAL HTTPS / private-CA path of the verifier.

Spins up an actual TLS server (self-signed cert acting as its own CA) that serves
OIDC discovery + JWKS, then drives the full verify_token() over HTTPS:

  * with OIDC_CA_BUNDLE pointing at the CA  -> discovery+JWKS fetch succeeds, token verifies.
  * without it (system trust store)         -> TLS verification REJECTS the self-signed cert,
                                               proving certificate verification is never disabled.

Uses only stdlib (http.server, ssl, threading) + cryptography/pyjwt (already deps).
"""
import datetime
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
import ssl as _ssl
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import src.utils.auth.token_verifier as tv

KID = "tls-test-kid"


def _make_self_signed(tmp_path):
    """Self-signed cert for CN=localhost (SAN localhost). Returns (cert_pem_path, key_pem_path)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "ca.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    return str(cert_path), str(key_path)


@pytest.fixture
def https_oidc(tmp_path):
    """Start a TLS OIDC server; yield (base_url, signing_private_key, ca_pem_path)."""
    cert_path, key_path = _make_self_signed(tmp_path)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    jwks = {"keys": [jwk]}

    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def do_GET(self):
            base = holder["base"]
            if self.path.endswith("/.well-known/openid-configuration"):
                body = json.dumps({
                    "issuer": f"{base}/realms/testrealm",
                    "jwks_uri": f"{base}/realms/testrealm/protocol/openid-connect/certs",
                }).encode()
            elif self.path.endswith("/protocol/openid-connect/certs"):
                body = json.dumps(jwks).encode()
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    port = httpd.socket.getsockname()[1]
    holder["base"] = f"https://localhost:{port}"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield holder["base"], signing_key, cert_path
    finally:
        httpd.shutdown()


def _token(signing_key, base):
    return jwt.encode(
        {"iss": f"{base}/realms/testrealm", "sub": "u", "aud": "amfa",
         "exp": int(time.time()) + 300},
        signing_key, algorithm="RS256", headers={"kid": KID},
    )


def _configure(monkeypatch, base, ca_bundle):
    monkeypatch.setattr(tv, "OIDC_TRUSTED_BASE_URLS", [base])
    monkeypatch.setattr(tv, "OIDC_VERIFY_AUDIENCE", False)
    monkeypatch.setattr(tv, "OIDC_CLOCK_SKEW_LEEWAY", 30)
    monkeypatch.setattr(tv, "OIDC_DISCOVERY_TIMEOUT", 5)
    monkeypatch.setattr(tv, "OIDC_CA_BUNDLE", ca_bundle)
    tv._jwks_clients.clear()
    tv._key_cache.clear()


def test_https_verify_succeeds_with_ca_bundle(https_oidc, monkeypatch):
    base, signing_key, ca = https_oidc
    _configure(monkeypatch, base, ca)  # trust the private CA
    principal = tv.verify_token(_token(signing_key, base))
    assert principal.realm == "testrealm"  # real discovery+JWKS over HTTPS, TLS verified


def test_https_verify_rejects_untrusted_cert_without_ca_bundle(https_oidc, monkeypatch):
    base, signing_key, _ = https_oidc
    _configure(monkeypatch, base, None)  # system trust only -> self-signed cert untrusted
    with pytest.raises(tv.AuthError) as e:
        tv.verify_token(_token(signing_key, base))
    # discovery fetch fails TLS verification -> fail closed (proves verification NOT disabled)
    assert e.value.status_code == 503

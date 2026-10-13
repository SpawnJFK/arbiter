"""OpenID Connect SSO against a fake IdP: local RSA keys, httpx.MockTransport for discovery,
JWKS, the token endpoint and DNS-over-HTTPS. No test reaches the network."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from platform_helpers import admin, client, org_id, register
from sqlalchemy import select, update

from arbiter.models import AuditEvent, SsoConfig, SsoState, User, utcnow
from arbiter.platform import sso

ISSUER = "https://idp.example.com"
CLIENT_ID = "arbiter-client"
CLIENT_SECRET = "idp-client-secret-value"
DOMAIN = "acme.example"


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeIdP:
    def __init__(self) -> None:
        self.key = _key()
        self.kid = "k1"
        self.codes: dict[str, dict] = {}  # code -> {"challenge", "claims"}
        self.txt: dict[str, list[str]] = {}
        self.token_auth: list[str] = []
        self.sign_key = self.key  # swap to sign with a key that is not in the JWKS
        self.alg = "RS256"

    def jwk(self) -> dict:
        j = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {**j, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def id_token(self, claims: dict) -> str:
        if self.alg == "HS256":
            return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": self.kid})
        return jwt.encode(claims, self.sign_key, algorithm=self.alg, headers={"kid": self.kid})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if url == f"{ISSUER}/jwks":
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if url == f"{ISSUER}/token" and request.method == "POST":
            self.token_auth.append(request.headers.get("authorization", ""))
            form = parse_qs(request.content.decode())
            entry = self.codes.get(form["code"][0])
            if entry is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            verifier = form["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            )
            if challenge != entry["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "pkce"})
            return httpx.Response(
                200, json={"id_token": self.id_token(entry["claims"]), "token_type": "Bearer"}
            )
        if request.url.host == "cloudflare-dns.com":
            name = request.url.params["name"]
            answers = [{"name": name, "type": 16, "data": f'"{t}"'} for t in self.txt.get(name, [])]
            return httpx.Response(200, json={"Status": 0, "Answer": answers})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdP()
    monkeypatch.setattr(sso, "_transport", httpx.MockTransport(fake.handler))
    sso.clear_caches()
    yield fake
    sso.clear_caches()


def _configure(c, pm, **extra) -> dict:
    body = {
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "allowed_domains": [DOMAIN],
        **extra,
    }
    r = c.put("/v1/org/sso", headers=pm, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _verify_dns(c, pm, idp: FakeIdP) -> None:
    cfg = c.get("/v1/org/sso", headers=pm).json()
    idp.txt[DOMAIN] = ["v=spf1 -all", cfg["domains"][0]["txt_record"]]
    r = c.post(f"/v1/org/sso/domains/{DOMAIN}/verify", headers=pm)
    assert r.status_code == 200, r.text
    assert r.json()["domains"][0]["verified"] is True


def _start(c, email: str, next_path: str | None = None) -> dict:
    params = {"email": email}
    if next_path:
        params["next"] = next_path
    r = c.get("/v1/auth/sso/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == f"{ISSUER}/authorize"
    return {k: v[0] for k, v in parse_qs(loc.query).items()}


def _claims(q: dict, **over) -> dict:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "idp-user-1",
        "email": "jane@acme.example",
        "email_verified": True,
        "name": "Jane Doe",
        "nonce": q["nonce"],
        "iat": now,
        "exp": now + 300,
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _login(c, idp: FakeIdP, email: str = "jane@acme.example", next_path: str | None = None, **claims):
    q = _start(c, email, next_path)
    assert q["code_challenge_method"] == "S256" and q["client_id"] == CLIENT_ID
    assert q["redirect_uri"].endswith("/api/sso/callback")
    code = f"code-{len(idp.codes)}"
    idp.codes[code] = {"challenge": q["code_challenge"], "claims": _claims(q, email=email, **claims)}
    return c.get("/v1/auth/sso/callback", params={"code": code, "state": q["state"]}), q


def test_full_login_jit_provisions_and_audits(db, idp):
    c = client()
    pm = register(c)
    cfg = _configure(c, pm)
    assert cfg["client_secret_set"] is True and "client_secret" not in cfg
    assert cfg["domains"][0]["verified"] is False and cfg["domains"][0]["txt_record"].startswith(
        "arbiter-verify="
    )
    stored = db.get(SsoConfig, org_id(c, pm))
    assert CLIENT_SECRET not in stored.client_secret_enc  # encrypted at rest

    # unverified domain: no SSO yet
    assert c.get("/v1/auth/sso/check", params={"email": "jane@acme.example"}).json() == {
        "sso": False,
        "enforced": False,
    }
    assert (
        c.get("/v1/auth/sso/start", params={"email": "jane@acme.example"}, follow_redirects=False).status_code
        == 404
    )
    _verify_dns(c, pm, idp)
    assert c.get("/v1/auth/sso/check", params={"email": "Jane@ACME.example"}).json() == {
        "sso": True,
        "enforced": False,
    }

    r, q = _login(c, idp, next_path="/app/projects")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["user"]["email"] == "jane@acme.example" and out["user"]["role"] == "client"
    assert out["redirect"] == "/app/projects"
    assert idp.token_auth[-1].startswith("Basic ")  # client_secret_basic by default
    me = c.get("/v1/me", headers={"Authorization": f"Bearer {out['token']}"}).json()
    assert me["org"]["id"] == org_id(c, pm) and me["user"]["name"] == "Jane Doe"

    actions = [e.action for e in db.execute(select(AuditEvent).order_by(AuditEvent.at)).scalars()]
    assert {"sso.created", "sso.domain_verified", "user.provisioned", "auth.sso_login"} <= set(actions)

    # the state is single use
    r2 = c.get("/v1/auth/sso/callback", params={"code": "code-0", "state": q["state"]})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "sso_failed"

    # second login reuses the account
    r3, _ = _login(c, idp)
    assert r3.status_code == 200 and r3.json()["user"]["id"] == out["user"]["id"]
    assert db.execute(select(User).where(User.email == "jane@acme.example")).scalars().all().__len__() == 1


@pytest.mark.parametrize(
    "case",
    [
        "nonce",
        "audience",
        "issuer",
        "expired",
        "unverified_email",
        "no_email",
        "bad_signature",
        "hs256",
        "multi_aud",
    ],
)
def test_id_token_validation_rejects(db, idp, case):
    c = client()
    pm = register(c)
    _configure(c, pm)
    _verify_dns(c, pm, idp)
    over: dict = {
        "nonce": {"nonce": "wrong"},
        "audience": {"aud": "someone-else"},
        "issuer": {"iss": "https://evil.example.com"},
        "expired": {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        "unverified_email": {"email_verified": False},
        "no_email": {},
        "bad_signature": {},
        "hs256": {},
        "multi_aud": {"aud": [CLIENT_ID, "other"], "azp": "other"},
    }[case]
    if case == "bad_signature":
        idp.sign_key = _key()
    if case == "hs256":
        idp.alg = "HS256"
    if case == "no_email":
        q = _start(c, "jane@acme.example")
        claims = _claims(q)
        del claims["email"]
        idp.codes["c"] = {"challenge": q["code_challenge"], "claims": claims}
        r = c.get("/v1/auth/sso/callback", params={"code": "c", "state": q["state"]})
    else:
        r, _ = _login(c, idp, **over)
    assert r.status_code == 401, (case, r.text)
    assert r.json()["error"]["code"] == "sso_failed"
    assert db.execute(select(User).where(User.email == "jane@acme.example")).scalar_one_or_none() is None


def test_email_outside_verified_domains_and_other_org_account(db, idp):
    c = client()
    pm = register(c)
    _configure(c, pm)
    _verify_dns(c, pm, idp)
    # IdP asserts an email in a domain the org does not own
    r, _ = _login(c, idp, email="jane@acme.example", **{})
    assert r.status_code == 200
    q = _start(c, "bob@acme.example")
    idp.codes["x"] = {"challenge": q["code_challenge"], "claims": _claims(q, email="bob@other.example")}
    r = c.get("/v1/auth/sso/callback", params={"code": "x", "state": q["state"]})
    assert r.status_code == 403
    # an existing account of another org is never taken over
    register(c, "mallory@acme.example", "Other Org")
    r, _ = _login(c, idp, email="mallory@acme.example")
    assert r.status_code == 409


def test_expired_state_and_pkce_mismatch(db, idp):
    c = client()
    pm = register(c)
    _configure(c, pm)
    _verify_dns(c, pm, idp)
    q = _start(c, "jane@acme.example")
    db.execute(update(SsoState).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    idp.codes["c"] = {"challenge": q["code_challenge"], "claims": _claims(q)}
    assert c.get("/v1/auth/sso/callback", params={"code": "c", "state": q["state"]}).status_code == 401
    q = _start(c, "jane@acme.example")
    idp.codes["d"] = {"challenge": "not-the-challenge", "claims": _claims(q)}
    r = c.get("/v1/auth/sso/callback", params={"code": "d", "state": q["state"]})
    assert r.status_code == 401 and "token exchange failed" in r.json()["error"]["message"]


def test_enforce_sso_blocks_password_login(db, idp):
    c = client()
    pm = register(c)
    r = c.put(
        "/v1/org/sso",
        headers=pm,
        json={
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "allowed_domains": [DOMAIN],
            "enforce_sso": True,
        },
    )
    assert r.status_code == 422  # no verified domain yet: enforcing would lock everyone out
    _configure(c, pm)
    _verify_dns(c, pm, idp)
    cfg = _configure(c, pm, client_secret=None, enforce_sso=True)  # secret kept when omitted
    assert cfg["enforce_sso"] is True and cfg["client_secret_set"] is True
    r = c.post("/v1/auth/login", json={"email": "pm@example.com", "password": "secret-123"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "sso_required"
    assert c.get("/v1/auth/sso/check", params={"email": "x@acme.example"}).json()["enforced"] is True
    r, _ = _login(c, idp)  # SSO still works, with the stored (decrypted) secret
    assert r.status_code == 200


def test_sso_config_access_domains_and_admin_verify(db, idp):
    c = client()
    pm = register(c)
    other = register(c, "o@example.com", "Other")
    _configure(c, pm)
    r = c.put(
        "/v1/org/sso",
        headers=other,
        json={"issuer": ISSUER, "client_id": "x", "client_secret": "y", "allowed_domains": [DOMAIN]},
    )
    assert r.status_code == 409  # domain already claimed
    assert c.post(f"/v1/org/sso/domains/{DOMAIN}/verify", headers=other).status_code == 404
    # DNS record missing: not verified
    r = c.post(f"/v1/org/sso/domains/{DOMAIN}/verify", headers=pm)
    assert r.status_code == 422
    ops = admin(c, db)
    r = c.post(f"/v1/admin/sso-domains/{DOMAIN}/verify", headers=ops)
    assert r.status_code == 200 and r.json()["domains"][0]["verified"] is True
    # bad input
    bad = {"issuer": "http://idp.example.com", "client_id": "x", "client_secret": "y"}
    assert (
        c.put("/v1/org/sso", headers=other, json={**bad, "allowed_domains": ["not a domain"]}).status_code
        == 422
    )
    # the issuer must answer discovery
    r = c.put("/v1/org/sso", headers=other, json={**bad, "issuer": "https://nowhere.example.com"})
    assert r.status_code == 401
    # removing the config frees the domain
    assert c.delete("/v1/org/sso", headers=pm).status_code == 204
    assert c.get("/v1/org/sso", headers=pm).json()["configured"] is False
    _configure(c, other)


def test_sso_config_needs_org_manage(db, idp):
    c = client()
    pm = register(c)
    r = c.post("/v1/users/invite", headers=pm, json={"email": "cl@example.com", "role": "client"})
    tok = r.json()["invite_token"]
    cl = {
        "Authorization": "Bearer "
        + c.post("/v1/auth/invite/accept", json={"token": tok, "password": "secret-123"}).json()["token"]
    }
    assert c.get("/v1/org/sso", headers=cl).status_code == 403
    assert c.put("/v1/org/sso", headers=cl, json={"issuer": ISSUER, "client_id": "x"}).status_code == 403


def test_safe_next_rejects_offsite():
    assert sso.safe_next("//evil.example.com") == ""
    assert sso.safe_next("https://evil.example.com") == ""
    assert sso.safe_next("/app/jobs?x=1") == "/app/jobs?x=1"
    assert json.dumps(sso.safe_next(None)) == '""'

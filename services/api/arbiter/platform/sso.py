"""Single sign-on with OpenID Connect (authorization code flow + PKCE), one IdP per org.

Flow:
  1. GET /v1/auth/sso/start?email=  finds the org by the email's VERIFIED domain, stores a
     single-use login state (state, nonce, PKCE verifier) and redirects to the IdP.
  2. The IdP sends the browser to <web_base_url>/api/sso/callback; the web route calls
     GET /v1/auth/sso/callback?code=&state=, which exchanges the code (with the PKCE
     verifier), validates the id_token (signature via the IdP's JWKS, issuer, audience, azp,
     expiry, nonce), provisions the user just in time and returns our session token.

Domains: an email domain routes to at most one org and is used only after the org proved
control of it, with a DNS TXT record `arbiter-verify=<token>` on the domain (checked through
a DNS-over-HTTPS resolver, ARBITER_DOH_URL) or by a platform admin.

HTTP goes through `http_client()`; tests set `_transport` to an httpx.MockTransport so no
test ever reaches a real IdP. SAML is not supported (later item).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.errors import Conflict, Forbidden, Invalid, NotFound, ServiceError
from arbiter.models import Organization, Role, SsoConfig, SsoDomain, SsoState, User, utcnow
from arbiter.platform import secrets as secret_box
from arbiter.platform.audit import audit

ALLOWED_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CACHE_TTL = 3600.0

# Test seam: an httpx transport (MockTransport) used instead of the network.
_transport: httpx.BaseTransport | None = None
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class SsoError(ServiceError):
    code = "sso_failed"
    status = 401


class SsoRequired(ServiceError):
    code = "sso_required"
    status = 403


def http_client() -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=10.0, follow_redirects=False)


def clear_caches() -> None:
    _discovery_cache.clear()
    _jwks_cache.clear()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def redirect_uri() -> str:
    return f"{get_settings().web_base_url.rstrip('/')}/api/sso/callback"


def normalize_domain(d: str) -> str:
    d = d.strip().lower().lstrip("@").rstrip(".")
    if not _DOMAIN_RE.match(d):
        raise Invalid(f"not a valid email domain: {d!r}")
    return d


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


# ------------------------------------------------------------------ provider metadata


def _get_json(url: str) -> dict[str, Any]:
    try:
        with http_client() as c:
            r = c.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise SsoError(f"identity provider not reachable: {type(e).__name__}") from e
    if r.status_code != 200:
        raise SsoError(f"identity provider answered {r.status_code} for {url}")
    try:
        return r.json()
    except ValueError as e:
        raise SsoError("identity provider returned invalid JSON") from e


def discover(issuer: str) -> dict[str, Any]:
    issuer = issuer.rstrip("/")
    hit = _discovery_cache.get(issuer)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    doc = _get_json(f"{issuer}/.well-known/openid-configuration")
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise SsoError("discovery document issuer does not match the configured issuer")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(field):
            raise SsoError(f"discovery document has no {field}")
    _discovery_cache[issuer] = (time.monotonic() + _CACHE_TTL, doc)
    return doc


def _jwks(uri: str, refresh: bool = False) -> list[dict[str, Any]]:
    hit = _jwks_cache.get(uri)
    if hit and hit[0] > time.monotonic() and not refresh:
        return hit[1]
    keys = _get_json(uri).get("keys") or []
    _jwks_cache[uri] = (time.monotonic() + _CACHE_TTL, keys)
    return keys


def _signing_key(uri: str, kid: str | None, alg: str) -> Any:
    for attempt in (False, True):  # unknown kid: the IdP may have rotated, refetch once
        keys = [k for k in _jwks(uri, refresh=attempt) if k.get("use", "sig") == "sig"]
        match = [k for k in keys if k.get("kid") == kid] if kid else keys
        if len(match) == 1 or (match and kid):
            return jwt.PyJWK(match[0], algorithm=alg).key
    raise SsoError("no matching signing key in the identity provider's JWKS")


# ------------------------------------------------------------------ configuration


def config_view(db: Session, org_id: str) -> dict[str, Any]:
    cfg = db.get(SsoConfig, org_id)
    domains = db.execute(
        select(SsoDomain).where(SsoDomain.org_id == org_id).order_by(SsoDomain.domain)
    ).scalars()
    return {
        "configured": cfg is not None,
        "enabled": bool(cfg and cfg.enabled),
        "issuer": cfg.issuer if cfg else "",
        "client_id": cfg.client_id if cfg else "",
        "client_secret_set": bool(cfg and cfg.client_secret_enc),
        "default_role": cfg.default_role if cfg else "client",
        "default_role_id": cfg.default_role_id if cfg else None,
        "enforce_sso": bool(cfg and cfg.enforce_sso),
        "redirect_uri": redirect_uri(),
        "domains": [
            {
                "domain": d.domain,
                "verified": d.verified_at is not None,
                "verified_at": d.verified_at.isoformat() if d.verified_at else None,
                "txt_record": f"arbiter-verify={d.verification_token}",
            }
            for d in domains
        ],
    }


def save_config(db: Session, actor: Any, data: dict[str, Any]) -> dict[str, Any]:
    org_id = actor.org_id
    s = get_settings()
    issuer = data["issuer"].strip().rstrip("/")
    if not issuer.startswith("https://") and not (s.env in ("dev", "test") and issuer.startswith("http://")):
        raise Invalid("issuer must be an https URL")
    default_role = data.get("default_role") or "client"
    if default_role not in ("pm", "client"):
        raise Invalid("default_role must be pm or client")
    if default_role == "pm" and actor.role not in ("pm", "admin"):
        raise Forbidden("only a project manager can make pm the SSO default role")
    role_id = data.get("default_role_id")
    if role_id:
        r = db.get(Role, role_id)
        if r is None or r.org_id != org_id:
            raise NotFound("role not found")
        default_role = r.base_role
    domains = sorted({normalize_domain(d) for d in data.get("allowed_domains", [])})

    discover(issuer)  # fail early on a typo, before anyone gets locked out

    cfg = db.get(SsoConfig, org_id)
    created = cfg is None
    if cfg is None:
        if not data.get("client_secret"):
            raise Invalid("client_secret is required")
        cfg = SsoConfig(org_id=org_id, issuer=issuer, client_id=data["client_id"])
        db.add(cfg)
    cfg.issuer = issuer
    cfg.client_id = data["client_id"].strip()
    if data.get("client_secret"):
        cfg.client_secret_enc = secret_box.encrypt(data["client_secret"])
    cfg.default_role = default_role
    cfg.default_role_id = role_id or None
    cfg.enabled = bool(data.get("enabled", True))

    existing = {
        d.domain: d for d in db.execute(select(SsoDomain).where(SsoDomain.org_id == org_id)).scalars()
    }
    for name in domains:
        if name in existing:
            continue
        other = db.get(SsoDomain, name)
        if other is not None:
            raise Conflict(f"the domain {name} is already claimed by another organization")
        db.add(SsoDomain(domain=name, org_id=org_id, verification_token=secrets.token_hex(16)))
    for name, d in existing.items():
        if name not in domains:
            db.delete(d)
    db.flush()

    enforce = bool(data.get("enforce_sso", False))
    if enforce:
        verified = db.execute(
            select(SsoDomain.domain).where(SsoDomain.org_id == org_id, SsoDomain.verified_at.is_not(None))
        ).first()
        if not cfg.enabled or verified is None:
            raise Invalid("SSO can be enforced only when it is enabled and at least one domain is verified")
    cfg.enforce_sso = enforce
    db.flush()
    audit(
        db,
        actor,
        "sso.created" if created else "sso.updated",
        "sso_config",
        org_id,
        {
            "issuer": issuer,
            "client_id": cfg.client_id,
            "client_secret_changed": bool(data.get("client_secret")),
            "domains": domains,
            "default_role": default_role,
            "default_role_id": cfg.default_role_id,
            "enforce_sso": enforce,
            "enabled": cfg.enabled,
        },
    )
    return config_view(db, org_id)


def delete_config(db: Session, actor: Any) -> None:
    cfg = db.get(SsoConfig, actor.org_id)
    if cfg is None:
        raise NotFound("SSO is not configured")
    for d in db.execute(select(SsoDomain).where(SsoDomain.org_id == actor.org_id)).scalars():
        db.delete(d)
    db.delete(cfg)
    audit(db, actor, "sso.deleted", "sso_config", actor.org_id, {})


def dns_txt_records(domain: str) -> list[str]:
    """TXT records of `domain` via DNS-over-HTTPS (JSON API, as served by common resolvers)."""
    url = f"{get_settings().doh_url}?{urlencode({'name': domain, 'type': 'TXT'})}"
    try:
        with http_client() as c:
            r = c.get(url, headers={"Accept": "application/dns-json"})
        body = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for ans in body.get("Answer") or []:
        if ans.get("type") == 16:
            out.append("".join(re.findall(r'"([^"]*)"', ans.get("data", ""))) or ans.get("data", ""))
    return out


def verify_domain(db: Session, actor: Any, domain: str, *, by_admin: bool = False) -> dict[str, Any]:
    name = normalize_domain(domain)
    d = db.get(SsoDomain, name)
    if d is None or (not by_admin and d.org_id != actor.org_id):
        raise NotFound("domain not found")
    if d.verified_at is None:
        if not by_admin:
            expected = f"arbiter-verify={d.verification_token}"
            if expected not in dns_txt_records(name):
                raise Invalid(f"TXT record {expected} not found on {name}")
        d.verified_at = utcnow()
        audit(db, actor, "sso.domain_verified", "sso_domain", name, {"by_admin": by_admin}, org_id=d.org_id)
    return config_view(db, d.org_id)


# ------------------------------------------------------------------ login


def active_config_for(db: Session, email: str) -> tuple[SsoConfig, Organization]:
    domain = email_domain(email)
    d = db.get(SsoDomain, domain) if domain else None
    if d is None or d.verified_at is None:
        raise NotFound("single sign-on is not set up for this email domain")
    cfg = db.get(SsoConfig, d.org_id)
    org = db.get(Organization, d.org_id)
    if cfg is None or not cfg.enabled or org is None:
        raise NotFound("single sign-on is not set up for this email domain")
    return cfg, org


def safe_next(next_path: str | None) -> str:
    """Only same-site relative paths survive (no //host, no scheme)."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//") or "\\" in next_path:
        return ""
    return next_path[:500]


def start_login(db: Session, email: str, next_path: str | None = None) -> str:
    cfg, org = active_config_for(db, email)
    meta = discover(cfg.issuer)
    st = SsoState(
        state=secrets.token_urlsafe(32),
        org_id=org.id,
        nonce=secrets.token_urlsafe(24),
        code_verifier=secrets.token_urlsafe(64),
        next_path=safe_next(next_path),
        expires_at=utcnow() + timedelta(seconds=get_settings().sso_state_ttl_seconds),
    )
    db.add(st)
    db.flush()
    challenge = _b64url(hashlib.sha256(st.code_verifier.encode()).digest())
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri(),
        "scope": "openid email profile",
        "state": st.state,
        "nonce": st.nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "login_hint": email,
    }
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return f"{meta['authorization_endpoint']}{sep}{urlencode(params)}"


def _exchange(cfg: SsoConfig, meta: dict[str, Any], code: str, verifier: str) -> dict[str, Any]:
    secret = secret_box.decrypt(cfg.client_secret_enc) if cfg.client_secret_enc else ""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "code_verifier": verifier,
    }
    methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    auth = None
    if "client_secret_basic" in methods:
        auth = httpx.BasicAuth(cfg.client_id, secret)
    else:
        form.update(client_id=cfg.client_id, client_secret=secret)
    try:
        with http_client() as c:
            r = c.post(meta["token_endpoint"], data=form, auth=auth, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise SsoError(f"token endpoint not reachable: {type(e).__name__}") from e
    if r.status_code != 200:
        raise SsoError(f"token exchange failed ({r.status_code})")
    body = r.json()
    if not body.get("id_token"):
        raise SsoError("token response has no id_token")
    return body


def validate_id_token(cfg: SsoConfig, meta: dict[str, Any], id_token: str, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise SsoError("id_token is malformed") from e
    alg = header.get("alg", "")
    if alg not in ALLOWED_ALGS:
        raise SsoError(f"id_token algorithm {alg!r} is not allowed")
    key = _signing_key(meta["jwks_uri"], header.get("kid"), alg)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[alg],
            audience=cfg.client_id,
            issuer=meta["issuer"],
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise SsoError(f"id_token rejected: {e}") from e
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != cfg.client_id:
        raise SsoError("id_token azp does not match the client")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("id_token nonce does not match")
    if not claims.get("email"):
        raise SsoError("id_token has no email claim; request the email scope at the identity provider")
    if claims.get("email_verified") is False:
        raise SsoError("the identity provider says this email is not verified")
    return claims


def complete_login(db: Session, code: str, state: str) -> tuple[User, str]:
    st = db.get(SsoState, state)
    if st is None or st.used_at is not None or st.expires_at <= utcnow():
        raise SsoError("login attempt expired or already used; start again")
    # Single use even when validation below fails: commit now, the request transaction
    # rolls back on an error and would otherwise undo it.
    st.used_at = utcnow()
    db.commit()
    cfg = db.get(SsoConfig, st.org_id)
    org = db.get(Organization, st.org_id)
    if cfg is None or not cfg.enabled or org is None:
        raise SsoError("single sign-on is not enabled for this organization")
    meta = discover(cfg.issuer)
    tokens = _exchange(cfg, meta, code, st.code_verifier)
    claims = validate_id_token(cfg, meta, tokens["id_token"], st.nonce)

    email = str(claims["email"]).strip().lower()
    d = db.get(SsoDomain, email_domain(email))
    if d is None or d.org_id != org.id or d.verified_at is None:
        raise Forbidden("this email domain is not allowed for the organization's single sign-on")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    who = None
    if user is None:
        from arbiter.platform.team import unusable_password_hash

        user = User(
            email=email,
            name=str(claims.get("name") or claims.get("preferred_username") or ""),
            password_hash=unusable_password_hash(),
            role=cfg.default_role,
            role_id=cfg.default_role_id,
            org_id=org.id,
        )
        db.add(user)
        db.flush()
        who = _as_principal(user, org)
        audit(
            db,
            who,
            "user.provisioned",
            "user",
            user.id,
            {"email": email, "via": "sso", "role": user.role, "role_id": user.role_id},
        )
    elif user.org_id != org.id:
        raise Conflict("this email belongs to an account outside the organization")
    elif not user.is_active:
        raise SsoError("this account is deactivated")
    who = who or _as_principal(user, org)
    audit(
        db,
        who,
        "auth.sso_login",
        "user",
        user.id,
        {"issuer": meta["issuer"], "subject": str(claims.get("sub"))},
    )
    return user, st.next_path


def _as_principal(user: User, org: Organization) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(user=user, api_key=None, org=org)


def sso_enforced_for(db: Session, user: User) -> bool:
    if not user.org_id:
        return False
    cfg = db.get(SsoConfig, user.org_id)
    return bool(cfg and cfg.enabled and cfg.enforce_sso)

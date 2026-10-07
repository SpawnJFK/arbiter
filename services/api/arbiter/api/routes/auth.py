"""Auth and account: register, login, me, org settings, API keys."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from arbiter.agency.org import update_org
from arbiter.api import security
from arbiter.api.deps import DB, PM, Auth, Customer, Unauthorized
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import ApiKey, Organization, User, utcnow

router = APIRouter(tags=["auth"])


def user_view(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "org_id": u.org_id}


def org_view(o: Organization) -> dict[str, Any]:
    return {
        "id": o.id,
        "name": o.name,
        "slug": o.slug,
        "plan": o.plan,
        "default_tier": o.default_tier,
        "no_reviewer_policy": o.no_reviewer_policy,
        "ai_subprocessors_opt_in": o.ai_subprocessors_opt_in,
        "regulated": o.regulated,
        "vertical": o.vertical,
        "data_retention_days": o.data_retention_days,
    }


class RegisterIn(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    name: str = Field(default="", max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    # Plain str: login must never reject an address that registration or seeding accepted
    # (EmailStr refuses reserved domains such as the demo accounts' .test).
    email: str = Field(min_length=3, max_length=320)
    password: str


def _slug(db: DB, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    slug, n = base, 1
    while db.execute(
        select(func.count()).select_from(Organization).where(Organization.slug == slug)
    ).scalar_one():
        n += 1
        slug = f"{base}-{n}"
    return slug


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: DB) -> dict[str, Any]:
    email = body.email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflict("an account with this email already exists")
    org = Organization(name=body.org_name, slug=_slug(db, body.org_name))
    db.add(org)
    db.flush()
    user = User(
        email=email,
        name=body.name,
        password_hash=security.hash_password(body.password),
        role="pm",
        org_id=org.id,
    )
    db.add(user)
    db.flush()
    return {
        "token": security.issue_token(user.id, user.role, org.id),
        "user": user_view(user),
        "org": org_view(org),
    }


@router.post("/auth/login")
def login(body: LoginIn, db: DB) -> dict[str, Any]:
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if user is None or not user.is_active or not security.verify_password(user.password_hash, body.password):
        raise Unauthorized("wrong email or password")
    return {"token": security.issue_token(user.id, user.role, user.org_id), "user": user_view(user)}


@router.get("/me")
def me(p: Auth) -> dict[str, Any]:
    return {"user": user_view(p.user) if p.user else None, "org": org_view(p.org) if p.org else None}


@router.get("/org")
def get_org(p: Customer) -> dict[str, Any]:
    assert p.org is not None
    return org_view(p.org)


class OrgPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    default_tier: Literal["auto", "ai_review", "hybrid", "full"] | None = None
    no_reviewer_policy: Literal["wait", "ai_fallback", "partial"] | None = None
    ai_subprocessors_opt_in: bool | None = None
    regulated: bool | None = None
    vertical: str | None = Field(default=None, max_length=60)
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)


@router.patch("/org")
def patch_org(body: OrgPatch, p: PM) -> dict[str, Any]:
    org = p.org
    assert org is not None
    update_org(org, body.model_dump(exclude_none=True))  # R-SEG-12 rules live in agency.org
    return org_view(org)


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list)


def _key_view(k: ApiKey) -> dict[str, Any]:
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "scopes": k.scopes,
        "created_at": k.created_at.isoformat(),
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    }


@router.get("/api-keys")
def list_keys(p: PM, db: DB) -> dict[str, Any]:
    keys = db.execute(
        select(ApiKey)
        .where(ApiKey.org_id == p.org_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at)
    ).scalars()
    return {"items": [_key_view(k) for k in keys], "next_offset": None}


@router.post("/api-keys", status_code=201)
def create_key(body: ApiKeyIn, p: PM, db: DB) -> dict[str, Any]:
    if p.role == "api":
        raise Invalid("API keys cannot create API keys")
    full, prefix, secret_hash = security.new_api_key()
    k = ApiKey(org_id=p.org_id, name=body.name, prefix=prefix, secret_hash=secret_hash, scopes=body.scopes)
    db.add(k)
    db.flush()
    return {**_key_view(k), "key": full}


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: str, p: PM, db: DB) -> Response:
    k = db.get(ApiKey, key_id)
    if k is None or k.org_id != p.org_id:
        raise NotFound("API key not found")
    k.revoked_at = utcnow()
    return Response(status_code=204)

"""Request dependencies: DB session, the authenticated principal, role guards, pagination."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.api import security
from arbiter.config import get_settings
from arbiter.db import session_factory
from arbiter.errors import Forbidden, NotFound, ServiceError
from arbiter.models import ApiKey, Organization, ReviewerProfile, User, utcnow


class Unauthorized(ServiceError):
    code = "unauthorized"
    status = 401


def get_db() -> Iterator[Session]:
    """One transaction per request: committed on success, rolled back on any error."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    user: User | None
    role: str  # admin | pm | client | reviewer | api
    org: Organization | None
    api_key: ApiKey | None = None

    @property
    def org_id(self) -> str:
        if self.org is None:
            raise Forbidden("this endpoint needs an organization account")
        return self.org.id


def current(db: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    parts = security.split_api_key(token)
    if parts:
        prefix, secret = parts
        key = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalar_one_or_none()
        if key is None or key.revoked_at is not None or not security.verify_password(key.secret_hash, secret):
            raise Unauthorized("invalid API key")
        key.last_used_at = utcnow()
        return Principal(user=None, role="api", org=db.get(Organization, key.org_id), api_key=key)
    claims = security.decode_token(token)
    if not claims:
        raise Unauthorized("invalid or expired token")
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("user not active")
    org = db.get(Organization, user.org_id) if user.org_id else None
    return Principal(user=user, role=user.role, org=org)


Auth = Annotated[Principal, Depends(current)]


def require(*roles: str):  # noqa: ANN201
    def dep(p: Auth) -> Principal:
        if p.role not in roles:
            raise Forbidden("not allowed for your role")
        return p

    return Depends(dep)


# Customer-side endpoints: org users and API keys.
CUSTOMER_ROLES = ("pm", "client", "api")
Customer = Annotated[Principal, require(*CUSTOMER_ROLES)]
PM = Annotated[Principal, require("pm", "api")]
Admin = Annotated[Principal, require("admin")]


def reviewer_profile(db: DB, p: Annotated[Principal, require("reviewer")]) -> ReviewerProfile:
    assert p.user is not None
    prof = db.execute(
        select(ReviewerProfile).where(ReviewerProfile.user_id == p.user.id)
    ).scalar_one_or_none()
    if prof is None:
        raise NotFound("reviewer profile not found")
    return prof


Reviewer = Annotated[ReviewerProfile, Depends(reviewer_profile)]


@dataclass
class Page:
    offset: int
    limit: int


def page(offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1)] = 50) -> Page:
    return Page(offset=offset, limit=min(limit, get_settings().page_size_max))


Paging = Annotated[Page, Depends(page)]


def listing(items: list, pg: Page, total_fetched: int | None = None) -> dict:
    """Callers fetch limit+1 rows; an extra row means there is a next page."""
    has_more = len(items) > pg.limit
    return {"items": items[: pg.limit], "next_offset": pg.offset + pg.limit if has_more else None}

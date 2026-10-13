"""Password reset (team invitations are accepted at /v1/auth/invite/accept, see routes/platform.py).

    POST /v1/auth/password/forgot  {email}            -> 202 {ok: true}   (always the same answer)
    POST /v1/auth/password/reset   {token, password}  -> 200 {token, user} (signed in)

Tokens are single use, expire (ARBITER_PASSWORD_RESET_TTL_MINUTES) and only their SHA-256
is stored. Asking again invalidates the
previous link. `forgot` never reveals whether an address has an account.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import update

from arbiter import notify
from arbiter.api import security
from arbiter.api.deps import DB
from arbiter.api.routes.auth import user_view
from arbiter.errors import Invalid
from arbiter.models import AccountToken, utcnow

router = APIRouter(tags=["auth"])


class InvalidToken(Invalid):
    code = "invalid_token"


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/auth/password/forgot", status_code=202)
def forgot(body: ForgotIn, db: DB) -> JSONResponse:
    notify.request_password_reset(db, body.email)
    return JSONResponse({"ok": True}, status_code=202)


@router.post("/auth/password/reset")
def reset(body: ResetIn, db: DB) -> dict[str, Any]:
    user = notify.consume_token(db, body.token, ("reset",))
    if user is None or not user.is_active:
        raise InvalidToken("this link is invalid or has expired; ask for a new one")
    user.password_hash = security.hash_password(body.password)
    # Every other outstanding link of this user stops working too.
    db.execute(
        update(AccountToken)
        .where(AccountToken.user_id == user.id, AccountToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    db.flush()
    return {"token": security.issue_token(user.id, user.role, user.org_id), "user": user_view(user)}

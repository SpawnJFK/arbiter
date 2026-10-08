"""UI string localization: public reads (no auth) and platform-admin writes.

English is the implicit source (the catalog lives in the web repo) and is always listed
first. Non-admins see enabled locales only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from arbiter import i18n
from arbiter.agency.common import normalize_locale
from arbiter.api.deps import DB, Admin, Unauthorized, current
from arbiter.errors import ServiceError

router = APIRouter(tags=["i18n"])


def _is_admin(db: DB, authorization: str | None) -> bool:
    """Optional auth: anonymous and non-admin callers get the public view."""
    if not authorization:
        return False
    try:
        return current(db, authorization).role == "admin"
    except (Unauthorized, ServiceError):
        return False


@router.get("/i18n/locales")
def list_locales(db: DB, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    return {"items": i18n.list_locales(db, include_disabled=_is_admin(db, authorization))}


@router.get("/i18n/messages/{locale}")
def get_messages(locale: str, db: DB, authorization: Annotated[str | None, Header()] = None) -> Response:
    loc = normalize_locale(locale)
    admin = _is_admin(db, authorization)
    out = {"locale": loc, "messages": i18n.messages_for(db, loc, include_disabled=admin)}
    cache = "no-store" if admin else "public, max-age=60"
    return JSONResponse(out, headers={"Cache-Control": cache})


class LocaleIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    enabled: bool | None = None


class MessagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: dict[str, str]
    mode: Literal["merge", "replace"] = "merge"
    # Optional English source {key: english}: values whose {placeholders} differ are rejected.
    source: dict[str, str] | None = None


@router.put("/admin/i18n/locales/{locale}")
def put_locale(locale: str, body: LocaleIn, p: Admin, db: DB) -> dict[str, Any]:
    loc = i18n.upsert_locale(db, normalize_locale(locale), body.name, body.enabled)
    return i18n.locale_view(db, loc)


@router.put("/admin/i18n/messages/{locale}")
def put_messages(locale: str, body: MessagesIn, p: Admin, db: DB) -> dict[str, Any]:
    return i18n.import_messages(db, normalize_locale(locale), body.messages, body.mode, body.source)


@router.delete("/admin/i18n/locales/{locale}", status_code=204)
def delete_locale(locale: str, p: Admin, db: DB) -> Response:
    i18n.delete_locale(db, normalize_locale(locale))
    return Response(status_code=204)

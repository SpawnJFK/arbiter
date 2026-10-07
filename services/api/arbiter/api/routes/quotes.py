"""Quotes: POST /quotes (analysis + price per tier), GET /quotes/{id}."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from arbiter.agency import crm, pricelists
from arbiter.api.deps import DB, Customer
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.billing.quotes import build_quote, quote_view
from arbiter.errors import Invalid, NotFound
from arbiter.models import FileAsset, Quote, utcnow

router = APIRouter(tags=["quotes"])


class QuoteIn(BaseModel):
    file_id: str = Field(min_length=1, max_length=40)
    target_langs: list[str] = Field(min_length=1, max_length=50)
    content_type: str = Field(default="general", min_length=1, max_length=60)
    # Agency OS: quote with this CRM account's price list (org default rates without one).
    account_id: str | None = Field(default=None, min_length=1, max_length=40)


def _view(q: Quote) -> dict[str, Any]:
    out = quote_view(q)
    # An open quote past valid_until reads as expired; housekeeping flips the row and
    # emits quote.expired, so the GET never writes.
    if q.status == "open" and q.valid_until < utcnow():
        out["status"] = "expired"
    return out


@router.post("/quotes", status_code=201)
def create_quote(
    body: QuoteIn,
    p: Customer,
    db: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    """R-SEG-12: tiers without a human are returned unavailable for regulated orgs."""
    payload = body.model_dump(mode="json")
    replay = idempotent_replay(db, p, "quotes", idempotency_key, payload)
    if replay is not None:
        return replay
    org = p.org
    assert org is not None
    fa = db.get(FileAsset, body.file_id)
    if fa is None or fa.org_id != org.id or fa.deleted_at is not None:
        raise NotFound("file not found")
    price_list = None
    if body.account_id:
        acc = crm.get_account(db, org.id, body.account_id)
        if acc.status != "active":
            raise Invalid("this account is archived")
        if acc.price_list_id:
            pl = pricelists.get_price_list(db, org.id, acc.price_list_id, include_archived=True)
            price_list = pl if pl.archived_at is None else None  # archived list: org default rates
    quote = build_quote(
        db, org, fa, body.target_langs, body.content_type, price_list=price_list, account_id=body.account_id
    )
    out = _view(quote)
    idempotent_store(db, p, "quotes", idempotency_key, payload, 201, out)
    return JSONResponse(out, status_code=201)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str, p: Customer, db: DB) -> dict[str, Any]:
    q = db.get(Quote, quote_id)
    if q is None or q.org_id != p.org_id:
        raise NotFound("quote not found")
    return _view(q)

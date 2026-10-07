"""Price lists (Agency OS). Roles: pm or API key. DELETE archives (accounts and quotes keep the link)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header
from sqlalchemy import func, select

from arbiter.agency import pricelists
from arbiter.agency.schemas import PriceListIn, PriceListPatch
from arbiter.api.deps import DB, PM, Paging, listing
from arbiter.api.routes.projects import idempotent_post
from arbiter.models import PriceList

router = APIRouter(tags=["price-lists"])


@router.get("/price-lists")
def list_price_lists(p: PM, db: DB, pg: Paging, include_archived: bool = False) -> dict[str, Any]:
    stmt = select(PriceList).where(PriceList.org_id == p.org_id)
    if not include_archived:
        stmt = stmt.where(PriceList.archived_at.is_(None))
    rows = list(
        db.execute(
            stmt.order_by(func.lower(PriceList.name), PriceList.id).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    return listing([pricelists.price_list_view(r) for r in rows], pg)


@router.post("/price-lists", status_code=201)
def create_price_list(
    body: PriceListIn, p: PM, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    def make() -> dict[str, Any]:
        return pricelists.price_list_view(pricelists.create_price_list(db, p.org_id, body))

    return idempotent_post(db, p, "price_lists", idempotency_key, body.model_dump(mode="json"), make)


@router.get("/price-lists/{price_list_id}")
def get_price_list(price_list_id: str, p: PM, db: DB) -> dict[str, Any]:
    return pricelists.price_list_view(
        pricelists.get_price_list(db, p.org_id, price_list_id, include_archived=True)
    )


@router.patch("/price-lists/{price_list_id}")
def patch_price_list(price_list_id: str, body: PriceListPatch, p: PM, db: DB) -> dict[str, Any]:
    pl = pricelists.get_price_list(db, p.org_id, price_list_id)
    return pricelists.price_list_view(pricelists.update_price_list(db, pl, body))


@router.delete("/price-lists/{price_list_id}")
def delete_price_list(price_list_id: str, p: PM, db: DB) -> dict[str, Any]:
    pl = pricelists.get_price_list(db, p.org_id, price_list_id, include_archived=True)
    return pricelists.price_list_view(pricelists.archive_price_list(db, pl))

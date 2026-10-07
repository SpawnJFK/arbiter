"""CRM (Agency OS): accounts, contacts, deals, activities. Roles: pm or API key.

Every lookup is scoped by org: an object of another org is a 404, never a 403.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Response
from sqlalchemy import func, select

from arbiter.agency import crm
from arbiter.agency.schemas import (
    AccountIn,
    AccountPatch,
    ActivityIn,
    ActivityPatch,
    ContactIn,
    ContactPatch,
    DealIn,
    DealPatch,
    DealStage,
)
from arbiter.api.deps import DB, PM, Paging, Principal, listing
from arbiter.api.routes.projects import idempotent_post
from arbiter.models import CrmAccount, CrmActivity, CrmContact, CrmDeal

router = APIRouter(tags=["crm"])

IdemKey = Annotated[str | None, Header()]


def _uid(p: Principal) -> str | None:
    return p.user.id if p.user is not None else None


# --------------------------------------------------------------------------- accounts


@router.get("/crm/accounts")
def list_accounts(
    p: PM,
    db: DB,
    pg: Paging,
    kind: Literal["client", "prospect"] | None = None,
    status: Literal["active", "archived"] | None = "active",
    q: str | None = None,
) -> dict[str, Any]:
    stmt = select(CrmAccount).where(CrmAccount.org_id == p.org_id)
    if kind:
        stmt = stmt.where(CrmAccount.kind == kind)
    if status:
        stmt = stmt.where(CrmAccount.status == status)
    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(CrmAccount.name.ilike(f"%{needle}%", escape="\\"))
    rows = list(
        db.execute(
            stmt.order_by(func.lower(CrmAccount.name), CrmAccount.id).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    return listing([crm.account_view(a) for a in rows], pg)


@router.post("/crm/accounts", status_code=201)
def create_account(body: AccountIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    def make() -> dict[str, Any]:
        assert p.org is not None
        acc = crm.create_account(db, p.org, body, _uid(p))
        return crm.account_detail(db, p.org_id, acc)

    return idempotent_post(db, p, "crm.accounts", idempotency_key, body.model_dump(mode="json"), make)


@router.get("/crm/accounts/{account_id}")
def get_account(account_id: str, p: PM, db: DB) -> dict[str, Any]:
    return crm.account_detail(db, p.org_id, crm.get_account(db, p.org_id, account_id))


@router.patch("/crm/accounts/{account_id}")
def patch_account(account_id: str, body: AccountPatch, p: PM, db: DB) -> dict[str, Any]:
    assert p.org is not None
    acc = crm.update_account(db, p.org, crm.get_account(db, p.org_id, account_id, lock=True), body)
    return crm.account_detail(db, p.org_id, acc)


@router.delete("/crm/accounts/{account_id}")
def delete_account(account_id: str, p: PM, db: DB) -> dict[str, Any]:
    """Archives (status archived); projects, jobs and deals keep pointing at the account."""
    acc = crm.archive_account(db, crm.get_account(db, p.org_id, account_id, lock=True))
    return crm.account_detail(db, p.org_id, acc)


# --------------------------------------------------------------------------- contacts


@router.get("/crm/accounts/{account_id}/contacts")
def list_contacts(account_id: str, p: PM, db: DB, pg: Paging) -> dict[str, Any]:
    acc = crm.get_account(db, p.org_id, account_id)
    rows = list(
        db.execute(
            select(CrmContact)
            .where(CrmContact.org_id == p.org_id, CrmContact.account_id == acc.id)
            .order_by(CrmContact.is_primary.desc(), CrmContact.name, CrmContact.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([crm.contact_view(c) for c in rows], pg)


@router.post("/crm/accounts/{account_id}/contacts", status_code=201)
def create_contact(account_id: str, body: ContactIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    def make() -> dict[str, Any]:
        acc = crm.get_account(db, p.org_id, account_id)
        return crm.contact_view(crm.create_contact(db, p.org_id, acc, body))

    payload = {"account_id": account_id, **body.model_dump(mode="json")}
    return idempotent_post(db, p, "crm.contacts", idempotency_key, payload, make)


@router.patch("/crm/contacts/{contact_id}")
def patch_contact(contact_id: str, body: ContactPatch, p: PM, db: DB) -> dict[str, Any]:
    return crm.contact_view(crm.update_contact(db, crm.get_contact(db, p.org_id, contact_id), body))


@router.delete("/crm/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: str, p: PM, db: DB) -> Response:
    db.delete(crm.get_contact(db, p.org_id, contact_id))
    return Response(status_code=204)


# --------------------------------------------------------------------------- deals


@router.get("/crm/deals")
def list_deals(
    p: PM, db: DB, pg: Paging, stage: DealStage | None = None, account_id: str | None = None
) -> dict[str, Any]:
    stmt = select(CrmDeal).where(CrmDeal.org_id == p.org_id)
    if stage:
        stmt = stmt.where(CrmDeal.stage == stage)
    if account_id:
        stmt = stmt.where(CrmDeal.account_id == account_id)
    rows = list(
        db.execute(
            stmt.order_by(CrmDeal.updated_at.desc(), CrmDeal.id).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    page = listing(rows, pg)
    page["items"] = crm.deals_view(db, page["items"])
    return page


@router.post("/crm/deals", status_code=201)
def create_deal(body: DealIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    def make() -> dict[str, Any]:
        return crm.deals_view(db, [crm.create_deal(db, p.org_id, body, _uid(p))])[0]

    return idempotent_post(db, p, "crm.deals", idempotency_key, body.model_dump(mode="json"), make)


@router.patch("/crm/deals/{deal_id}")
def patch_deal(deal_id: str, body: DealPatch, p: PM, db: DB) -> dict[str, Any]:
    deal = crm.update_deal(db, crm.get_deal(db, p.org_id, deal_id), body)
    return crm.deals_view(db, [deal])[0]


@router.delete("/crm/deals/{deal_id}")
def delete_deal(deal_id: str, p: PM, db: DB) -> dict[str, Any]:
    """Deletes the deal and returns it as it was; its activities stay on the account."""
    deal = crm.get_deal(db, p.org_id, deal_id)
    out = crm.deals_view(db, [deal])[0]
    db.delete(deal)
    return out


# --------------------------------------------------------------------------- activities


@router.get("/crm/activities")
def list_activities(
    p: PM,
    db: DB,
    pg: Paging,
    account_id: str | None = None,
    deal_id: str | None = None,
    open: bool | None = None,
) -> dict[str, Any]:
    stmt = select(CrmActivity).where(CrmActivity.org_id == p.org_id)
    if account_id:
        stmt = stmt.where(CrmActivity.account_id == account_id)
    if deal_id:
        stmt = stmt.where(CrmActivity.deal_id == deal_id)
    if open is True:
        stmt = stmt.where(CrmActivity.done.is_(False))
    elif open is False:
        stmt = stmt.where(CrmActivity.done.is_(True))
    order = (
        (CrmActivity.due_at.asc().nulls_last(), CrmActivity.created_at, CrmActivity.id)
        if open
        else (CrmActivity.created_at.desc(), CrmActivity.id.desc())
    )
    rows = list(db.execute(stmt.order_by(*order).offset(pg.offset).limit(pg.limit + 1)).scalars())
    return listing([crm.activity_view(a) for a in rows], pg)


@router.post("/crm/activities", status_code=201)
def create_activity(body: ActivityIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    def make() -> dict[str, Any]:
        return crm.activity_view(crm.create_activity(db, p.org_id, body, _uid(p)))

    return idempotent_post(db, p, "crm.activities", idempotency_key, body.model_dump(mode="json"), make)


@router.patch("/crm/activities/{activity_id}")
def patch_activity(activity_id: str, body: ActivityPatch, p: PM, db: DB) -> dict[str, Any]:
    return crm.activity_view(crm.update_activity(db, crm.get_activity(db, p.org_id, activity_id), body))

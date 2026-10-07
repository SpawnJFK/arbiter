"""CRM: accounts, contacts, deals, activities. Every lookup is scoped by org (404 across orgs).

Account stats (revenue is recognised when a job is delivered):
  projects       projects ordered for the account
  jobs_active    jobs in running | review | ready | merging
  revenue_total  sum of job revenue for delivered/settled/disputed jobs
  revenue_90d    the same, delivered in the last 90 days
  margin_90d     revenue_90d minus engine and reviewer cost of those jobs
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.agency.common import currency, iso, money
from arbiter.agency.schemas import (
    AccountIn,
    AccountPatch,
    ActivityIn,
    ActivityPatch,
    ContactIn,
    ContactPatch,
    DealIn,
    DealPatch,
)
from arbiter.errors import Invalid, NotFound
from arbiter.models import (
    CrmAccount,
    CrmActivity,
    CrmContact,
    CrmDeal,
    Job,
    Organization,
    PriceList,
    Project,
    Quote,
    WorkflowTemplate,
    utcnow,
)

ACTIVE_JOB_STATES = ("running", "review", "ready", "merging")
DELIVERED_JOB_STATES = ("delivered", "settled", "disputed")
DEAL_STAGES = ("lead", "qualified", "proposal", "negotiation", "won", "lost")
CLOSED_STAGES = ("won", "lost")


# --------------------------------------------------------------------------- lookups


def get_account(session: Session, org_id: str, account_id: str, *, lock: bool = False) -> CrmAccount:
    q = select(CrmAccount).where(CrmAccount.id == account_id, CrmAccount.org_id == org_id)
    if lock:
        q = q.with_for_update()
    acc = session.execute(q).scalar_one_or_none()
    if acc is None:
        raise NotFound("account not found")
    return acc


def find_account_by_name(session: Session, org_id: str, name: str) -> CrmAccount | None:
    return (
        session.execute(
            select(CrmAccount)
            .where(
                CrmAccount.org_id == org_id,
                func.lower(CrmAccount.name) == name.strip().lower(),
                CrmAccount.status == "active",
            )
            .order_by(CrmAccount.created_at)
        )
        .scalars()
        .first()
    )


def _get(session: Session, model: Any, org_id: str, obj_id: str, what: str) -> Any:
    obj = session.execute(
        select(model).where(model.id == obj_id, model.org_id == org_id)
    ).scalar_one_or_none()
    if obj is None:
        raise NotFound(f"{what} not found")
    return obj


def get_contact(session: Session, org_id: str, contact_id: str) -> CrmContact:
    return _get(session, CrmContact, org_id, contact_id, "contact")


def get_deal(session: Session, org_id: str, deal_id: str) -> CrmDeal:
    return _get(session, CrmDeal, org_id, deal_id, "deal")


def get_activity(session: Session, org_id: str, activity_id: str) -> CrmActivity:
    return _get(session, CrmActivity, org_id, activity_id, "activity")


def _check_links(session: Session, org_id: str, workflow_id: str | None, price_list_id: str | None) -> None:
    if workflow_id:
        wf = session.get(WorkflowTemplate, workflow_id)
        if wf is None or wf.org_id != org_id or wf.archived_at is not None:
            raise Invalid("workflow_template_id does not name a workflow of this organization")
    if price_list_id:
        pl = session.get(PriceList, price_list_id)
        if pl is None or pl.org_id != org_id or pl.archived_at is not None:
            raise Invalid("price_list_id does not name a price list of this organization")


# --------------------------------------------------------------------------- views


def account_view(a: CrmAccount) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "status": a.status,
        "industry": a.industry,
        "country": a.country,
        "vat_id": a.vat_id,
        "currency": a.currency,
        "default_tier": a.default_tier,
        "workflow_template_id": a.workflow_template_id,
        "price_list_id": a.price_list_id,
        "owner_user_id": a.owner_user_id,
        "notes": a.notes,
        "created_at": iso(a.created_at),
    }


def contact_view(c: CrmContact) -> dict[str, Any]:
    return {
        "id": c.id,
        "account_id": c.account_id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "role": c.role,
        "is_primary": c.is_primary,
        "created_at": iso(c.created_at),
    }


def deal_view(d: CrmDeal, account_name: str | None) -> dict[str, Any]:
    return {
        "id": d.id,
        "account_id": d.account_id,
        "account_name": account_name,
        "title": d.title,
        "value": money(d.value),
        "currency": d.currency,
        "stage": d.stage,
        "expected_close": iso(d.expected_close),
        "quote_id": d.quote_id,
        "lost_reason": d.lost_reason,
        "owner_user_id": d.owner_user_id,
        "closed_at": iso(d.closed_at),
        "created_at": iso(d.created_at),
        "updated_at": iso(d.updated_at),
    }


def deals_view(session: Session, deals: list[CrmDeal]) -> list[dict[str, Any]]:
    ids = {d.account_id for d in deals}
    names = (
        dict(session.execute(select(CrmAccount.id, CrmAccount.name).where(CrmAccount.id.in_(ids))).all())
        if ids
        else {}
    )
    return [deal_view(d, names.get(d.account_id)) for d in deals]


def activity_view(a: CrmActivity) -> dict[str, Any]:
    return {
        "id": a.id,
        "account_id": a.account_id,
        "deal_id": a.deal_id,
        "kind": a.kind,
        "body": a.body,
        "due_at": iso(a.due_at),
        "done": a.done,
        "done_at": iso(a.done_at),
        "user_id": a.user_id,
        "created_at": iso(a.created_at),
    }


def account_stats(session: Session, org_id: str, account_id: str) -> dict[str, Any]:
    since = utcnow() - timedelta(days=90)
    projects = session.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.org_id == org_id, Project.account_id == account_id)
    ).scalar_one()
    active = session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.org_id == org_id, Job.account_id == account_id, Job.state.in_(ACTIVE_JOB_STATES))
    ).scalar_one()
    zero = Decimal("0")
    total = session.execute(
        select(func.coalesce(func.sum(Job.revenue), zero)).where(
            Job.org_id == org_id, Job.account_id == account_id, Job.state.in_(DELIVERED_JOB_STATES)
        )
    ).scalar_one()
    rev90, cost90 = session.execute(
        select(
            func.coalesce(func.sum(Job.revenue), zero),
            func.coalesce(func.sum(Job.cost_engines + Job.cost_reviewers), zero),
        ).where(
            Job.org_id == org_id,
            Job.account_id == account_id,
            Job.state.in_(DELIVERED_JOB_STATES),
            Job.delivered_at >= since,
        )
    ).one()
    return {
        "projects": int(projects),
        "jobs_active": int(active),
        "revenue_total": money(total),
        "revenue_90d": money(rev90),
        "margin_90d": money(Decimal(rev90) - Decimal(cost90)),
    }


def account_detail(session: Session, org_id: str, acc: CrmAccount) -> dict[str, Any]:
    contacts = session.execute(
        select(CrmContact)
        .where(CrmContact.org_id == org_id, CrmContact.account_id == acc.id)
        .order_by(CrmContact.is_primary.desc(), CrmContact.name, CrmContact.id)
    ).scalars()
    deals = list(
        session.execute(
            select(CrmDeal)
            .where(CrmDeal.org_id == org_id, CrmDeal.account_id == acc.id)
            .order_by(CrmDeal.created_at.desc(), CrmDeal.id)
        ).scalars()
    )
    acts = session.execute(
        select(CrmActivity)
        .where(CrmActivity.org_id == org_id, CrmActivity.account_id == acc.id)
        .order_by(CrmActivity.created_at.desc(), CrmActivity.id.desc())
        .limit(20)
    ).scalars()
    return {
        **account_view(acc),
        "contacts": [contact_view(c) for c in contacts],
        "deals": [deal_view(d, acc.name) for d in deals],
        "recent_activities": [activity_view(a) for a in acts],
        "stats": account_stats(session, org_id, acc.id),
    }


# --------------------------------------------------------------------------- accounts


def create_account(
    session: Session, org: Organization, body: AccountIn, user_id: str | None = None
) -> CrmAccount:
    """R-SEG-12: a regulated org's account cannot default to a tier without a human."""
    if org.regulated and body.default_tier in ("auto", "ai_review"):
        raise Invalid("regulated organizations cannot use the auto or ai_review tier")
    _check_links(session, org.id, body.workflow_template_id, body.price_list_id)
    acc = CrmAccount(
        org_id=org.id,
        name=body.name,
        kind=body.kind,
        status="active",
        industry=body.industry or None,
        country=body.country.upper() if body.country else None,
        vat_id=body.vat_id or None,
        currency=currency(body.currency),
        default_tier=body.default_tier,
        workflow_template_id=body.workflow_template_id,
        price_list_id=body.price_list_id,
        owner_user_id=user_id,
        notes=body.notes,
    )
    session.add(acc)
    session.flush()
    return acc


def update_account(session: Session, org: Organization, acc: CrmAccount, body: AccountPatch) -> CrmAccount:
    data = body.model_dump(exclude_unset=True)
    if org.regulated and data.get("default_tier") in ("auto", "ai_review"):
        raise Invalid("regulated organizations cannot use the auto or ai_review tier")
    _check_links(session, org.id, data.get("workflow_template_id"), data.get("price_list_id"))
    for key in ("name", "kind", "status", "currency"):
        if key in data and data[key] is None:
            raise Invalid(f"{key} cannot be null")
    if "currency" in data:
        data["currency"] = currency(data["currency"])
    if data.get("country"):
        data["country"] = data["country"].upper()
    if "notes" in data and data["notes"] is None:
        data["notes"] = ""
    for k, v in data.items():
        setattr(acc, k, v)
    acc.updated_at = utcnow()
    session.flush()
    return acc


def archive_account(session: Session, acc: CrmAccount) -> CrmAccount:
    """DELETE archives: history (projects, jobs, deals) keeps pointing at the account."""
    acc.status = "archived"
    acc.updated_at = utcnow()
    session.flush()
    return acc


# --------------------------------------------------------------------------- contacts


def _unset_primary(session: Session, org_id: str, account_id: str, keep: str | None) -> None:
    for c in session.execute(
        select(CrmContact).where(
            CrmContact.org_id == org_id, CrmContact.account_id == account_id, CrmContact.is_primary.is_(True)
        )
    ).scalars():
        if c.id != keep:
            c.is_primary = False


def create_contact(session: Session, org_id: str, acc: CrmAccount, body: ContactIn) -> CrmContact:
    c = CrmContact(
        org_id=org_id,
        account_id=acc.id,
        name=body.name,
        email=str(body.email).lower() if body.email else None,
        phone=body.phone or None,
        role=body.role or None,
        is_primary=body.is_primary,
    )
    session.add(c)
    session.flush()
    if body.is_primary:
        _unset_primary(session, org_id, acc.id, c.id)
    return c


def update_contact(session: Session, c: CrmContact, body: ContactPatch) -> CrmContact:
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise Invalid("name cannot be empty")
    if data.get("email"):
        data["email"] = str(data["email"]).lower()
    if data.get("is_primary") is None:
        data.pop("is_primary", None)
    for k, v in data.items():
        setattr(c, k, v)
    if data.get("is_primary"):
        _unset_primary(session, c.org_id, c.account_id, c.id)
    session.flush()
    return c


# --------------------------------------------------------------------------- deals


def create_deal(session: Session, org_id: str, body: DealIn, user_id: str | None = None) -> CrmDeal:
    acc = get_account(session, org_id, body.account_id)
    if body.quote_id:
        q = session.get(Quote, body.quote_id)
        if q is None or q.org_id != org_id:
            raise Invalid("quote_id does not name a quote of this organization")
    d = CrmDeal(
        org_id=org_id,
        account_id=acc.id,
        title=body.title,
        value=body.value,
        currency=currency(body.currency, acc.currency),
        stage=body.stage,
        expected_close=body.expected_close,
        quote_id=body.quote_id,
        owner_user_id=user_id,
        closed_at=utcnow() if body.stage in CLOSED_STAGES else None,
    )
    session.add(d)
    session.flush()
    return d


def update_deal(session: Session, d: CrmDeal, body: DealPatch) -> CrmDeal:
    """Stage changes: entering won/lost sets closed_at; reopening clears it (and lost_reason)."""
    data = body.model_dump(exclude_unset=True)
    for key in ("stage", "value", "title"):
        if key in data and data[key] is None:
            raise Invalid(f"{key} cannot be null")
    new_stage = data.get("stage", d.stage)
    if new_stage != d.stage:
        if new_stage in CLOSED_STAGES:
            d.closed_at = utcnow()
        else:
            d.closed_at = None
            if "lost_reason" not in data:
                d.lost_reason = None
    for k, v in data.items():
        setattr(d, k, v)
    d.updated_at = utcnow()
    session.flush()
    return d


# --------------------------------------------------------------------------- activities


def create_activity(
    session: Session, org_id: str, body: ActivityIn, user_id: str | None = None
) -> CrmActivity:
    acc = get_account(session, org_id, body.account_id)
    if body.deal_id:
        deal = get_deal(session, org_id, body.deal_id)
        if deal.account_id != acc.id:
            raise Invalid("the deal belongs to another account")
    a = CrmActivity(
        org_id=org_id,
        account_id=acc.id,
        deal_id=body.deal_id,
        kind=body.kind,
        body=body.body,
        due_at=body.due_at,
        done=False,
        user_id=user_id,
    )
    session.add(a)
    session.flush()
    return a


def update_activity(session: Session, a: CrmActivity, body: ActivityPatch) -> CrmActivity:
    data = body.model_dump(exclude_unset=True)
    if "done" in data and data["done"] is not None and data["done"] != a.done:
        a.done = bool(data["done"])
        a.done_at = utcnow() if a.done else None
    if data.get("body"):
        a.body = data["body"]
    if "due_at" in data:
        a.due_at = data["due_at"]
    session.flush()
    return a

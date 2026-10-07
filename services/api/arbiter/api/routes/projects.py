"""Projects: POST /projects turns an accepted quote into jobs (one per target language).

Also home of the Idempotency-Key helpers shared by the customer POST endpoints: the key
is scoped to the org (`org_id:<header>`), kept 24 hours, and a replay with a different
body is a 409, never a silent second order.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Annotated, Any, Literal

import orjson
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from arbiter.agency import crm
from arbiter.agency import workflows as wfl
from arbiter.api.deps import DB, PM, Customer, Paging, Principal, listing
from arbiter.api.routes.jobs import jobs_view
from arbiter.billing.quotes import tier_allowed
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import (
    CrmAccount,
    FileAsset,
    IdempotencyRecord,
    Job,
    Organization,
    Project,
    Quote,
    WorkflowTemplate,
    utcnow,
)
from arbiter.pipeline import orchestrator

router = APIRouter(tags=["projects"])

IDEMPOTENCY_TTL = timedelta(hours=24)
CENT = Decimal("0.01")


# --------------------------------------------------------------------------- idempotency


class IdempotencyConflict(Conflict):
    code = "idempotency_conflict"


def _idem_key(p: Principal, header: str) -> str:
    """One key space per org (like Stripe): reusing a key on another endpoint is a 409."""
    return f"{p.org_id}:{header.strip()}"


def _hash(scope: str, payload: Any) -> str:
    return hashlib.sha256(
        scope.encode() + b"\0" + orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def idempotent_replay(
    db: Session, p: Principal, scope: str, header: str | None, payload: Any
) -> JSONResponse | None:
    """Return the stored response for a repeated Idempotency-Key, or None to proceed.

    Takes a transaction-scoped advisory lock on the key so two concurrent requests with the
    same key run one after the other: the second one then sees the first one's record.
    """
    if not header or not header.strip():
        return None
    if len(header) > 150:
        raise Invalid("Idempotency-Key is too long (max 150 characters)")
    key = _idem_key(p, header)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"idem:{key}"})
    rec = db.get(IdempotencyRecord, key)
    if rec is None:
        return None
    if rec.created_at < utcnow() - IDEMPOTENCY_TTL:
        db.delete(rec)
        db.flush()
        return None
    if rec.request_hash != _hash(scope, payload):
        raise IdempotencyConflict("this Idempotency-Key was already used with a different request")
    return JSONResponse(rec.body, status_code=rec.status_code)


def idempotent_store(
    db: Session, p: Principal, scope: str, header: str | None, payload: Any, status: int, body: Any
) -> None:
    if not header or not header.strip():
        return
    db.add(
        IdempotencyRecord(
            key=_idem_key(p, header),
            request_hash=_hash(scope, payload),
            status_code=status,
            body=body,
        )
    )
    db.flush()


def idempotent_post(
    db: Session,
    p: Principal,
    scope: str,
    header: str | None,
    payload: Any,
    make: Callable[[], dict[str, Any]],
    status: int = 201,
) -> Any:
    """Create-once wrapper for POST endpoints: replay, or run `make` and store its response."""
    replay = idempotent_replay(db, p, scope, header, payload)
    if replay is not None:
        return replay
    out = make()
    idempotent_store(db, p, scope, header, payload, status, out)
    return JSONResponse(out, status_code=status)


# --------------------------------------------------------------------------- views


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def project_view(prj: Project, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": prj.id,
        "name": prj.name,
        "quote_id": prj.quote_id,
        "source_lang": prj.source_lang,
        "target_langs": list(prj.target_langs or []),
        "tier": prj.tier,
        "content_type": prj.content_type,
        "due_at": _iso(prj.due_at),
        "account_id": prj.account_id,
        "workflow_template_id": prj.workflow_template_id,
        "created_at": _iso(prj.created_at),
    }
    if jobs is not None:
        out["jobs"] = jobs
    return out


def _project_jobs(db: Session, p: Principal, prj: Project) -> list[dict[str, Any]]:
    jobs = list(
        db.execute(
            select(Job).where(Job.project_id == prj.id, Job.org_id == p.org_id).order_by(Job.target_lang)
        ).scalars()
    )
    return jobs_view(db, p, jobs)


# --------------------------------------------------------------------------- routes


class TierNotAllowed(Invalid):
    code = "tier_not_allowed"


class QuoteExpired(Conflict):
    code = "quote_expired"


class QuoteNotOpen(Conflict):
    code = "quote_not_open"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quote_id: str = Field(min_length=1, max_length=40)
    # Optional when a workflow template decides the tier (Agency OS).
    tier: Literal["auto", "ai_review", "hybrid", "full"] | None = None
    due_at: datetime | None = None
    account_id: str | None = Field(default=None, min_length=1, max_length=40)
    workflow_template_id: str | None = Field(default=None, min_length=1, max_length=40)


def _resolve_workflow(
    db: Session, org: Organization, body: ProjectIn, acc: CrmAccount | None
) -> tuple[WorkflowTemplate | None, str]:
    """Which template and tier the jobs run with, most explicit first:
    1. body.workflow_template_id (its tier wins over body.tier)
    2. the account's workflow template, when body.tier is not given
    3. the org's default workflow template, when body.tier is not given
    4. no template: body.tier, else the account's default tier, else the org's default tier
    """
    if body.workflow_template_id:
        wf = wfl.get_workflow(db, org.id, body.workflow_template_id)
        return wf, wf.tier
    if body.tier is None:
        if acc is not None and acc.workflow_template_id:
            wf = db.get(WorkflowTemplate, acc.workflow_template_id)
            if wf is not None and wf.org_id == org.id and wf.archived_at is None:
                return wf, wf.tier
        default = (
            db.execute(
                select(WorkflowTemplate).where(
                    WorkflowTemplate.org_id == org.id,
                    WorkflowTemplate.is_default.is_(True),
                    WorkflowTemplate.archived_at.is_(None),
                )
            )
            .scalars()
            .first()
        )
        if default is not None:
            return default, default.tier
    tier = body.tier or (acc.default_tier if acc is not None else None) or org.default_tier
    return None, tier


def _split(total: Decimal, n: int) -> list[Decimal]:
    """Split a price evenly across n jobs in cents; the last job takes the rounding rest."""
    share = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    parts = [share] * n
    parts[-1] = total - share * (n - 1)
    return parts


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectIn,
    p: PM,
    db: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    """Accept a quote and start one job per target language.

    R-SEG-12: regulated organizations never get `auto` or `ai_review`; checked against the
    quote and against the org as it is now (it may have become regulated after quoting).
    Every job freezes its workflow snapshot (template or tier default) here.
    """
    payload = body.model_dump(mode="json")
    replay = idempotent_replay(db, p, "projects", idempotency_key, payload)
    if replay is not None:
        return replay
    org = p.org
    assert org is not None
    quote = db.execute(select(Quote).where(Quote.id == body.quote_id).with_for_update()).scalar_one_or_none()
    if quote is None or quote.org_id != org.id:
        raise NotFound("quote not found")
    if quote.status != "open":
        raise QuoteNotOpen(f"this quote is {quote.status}; request a new quote")
    if quote.valid_until < utcnow():
        raise QuoteExpired("this quote has expired; request a new quote")
    account_id = body.account_id or (quote.analysis or {}).get("account_id")
    acc = crm.get_account(db, org.id, account_id) if account_id else None
    if acc is not None and acc.status != "active":
        raise Invalid("this account is archived")
    template, tier = _resolve_workflow(db, org, body, acc)
    if not tier_allowed(quote, tier) or (org.regulated and tier in ("auto", "ai_review")):
        reason = (quote.tiers or {}).get(tier, {}).get("blocked_reason") or (
            "Regulated vertical: every segment needs a human reviewer (R-SEG-12)."
        )
        raise TierNotAllowed(f"the {tier} tier is not available for this order: {reason}")
    workflow = wfl.snapshot(template, tier)
    if body.due_at is not None and body.due_at.tzinfo is None:
        raise Invalid("due_at must include a time zone (ISO 8601, e.g. 2026-10-09T12:00:00Z)")
    fa = db.get(FileAsset, quote.file_id) if quote.file_id else None
    if fa is None or fa.org_id != org.id or fa.deleted_at is not None:
        raise Conflict("the quoted file is no longer available")

    langs = list(quote.target_langs or [])
    if not langs:
        raise Invalid("the quote has no target languages")
    tier_entry = (quote.tiers or {})[tier]
    price = Decimal(str(tier_entry["price"]))
    by_lang = (quote.analysis or {}).get("by_lang", {})

    prj = Project(
        org_id=org.id,
        name=body.name,
        source_lang=quote.source_lang,
        target_langs=langs,
        tier=tier,
        content_type=quote.content_type,
        due_at=body.due_at,
        quote_id=quote.id,
        created_by=p.user.id if p.user else None,
        account_id=acc.id if acc is not None else None,
        workflow_template_id=template.id if template is not None else None,
    )
    db.add(prj)
    db.flush()
    jobs: list[Job] = []
    for lang, revenue in zip(langs, _split(price, len(langs)), strict=True):
        info = by_lang.get(lang, {})
        est = 0.0 if tier == "full" else float(info.get("est_auto_rate", tier_entry.get("est_auto_rate", 0)))
        job = Job(
            project_id=prj.id,
            org_id=org.id,
            file_id=fa.id,
            source_lang=quote.source_lang,
            target_lang=lang,
            tier=tier,
            content_type=quote.content_type,
            state="quoted",
            account_id=acc.id if acc is not None else None,
            workflow=dict(workflow),
            due_at=body.due_at,
            revenue=revenue,
            est_auto_rate=est,
            weighted_words=float(info.get("weighted_words", 0) or 0),
        )
        db.add(job)
        jobs.append(job)
    db.flush()
    quote.status = "accepted"
    for job in jobs:
        orchestrator.start_job(db, job)
    db.flush()
    out = project_view(prj, jobs_view(db, p, jobs))
    idempotent_store(db, p, "projects", idempotency_key, payload, 201, out)
    return JSONResponse(out, status_code=201)


@router.get("/projects")
def list_projects(p: Customer, db: DB, pg: Paging, account_id: str | None = None) -> dict[str, Any]:
    q = select(Project).where(Project.org_id == p.org_id)
    if account_id:
        q = q.where(Project.account_id == account_id)
    rows = list(
        db.execute(
            q.order_by(Project.created_at.desc(), Project.id.desc()).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    return listing([project_view(r) for r in rows], pg)


@router.get("/projects/{project_id}")
def get_project(project_id: str, p: Customer, db: DB) -> dict[str, Any]:
    prj = db.get(Project, project_id)
    if prj is None or prj.org_id != p.org_id:
        raise NotFound("project not found")
    return project_view(prj, _project_jobs(db, p, prj))

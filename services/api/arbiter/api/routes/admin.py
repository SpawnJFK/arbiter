"""Platform-operator endpoints: reviewers, disputes, payouts, organizations, reviewer tests.

Payouts: POST /admin/payouts/run accrues what is owed (run_payouts) and sends it through
the configured PayoutProvider (send_payouts). No real provider exists yet. In dev, test and
staging the MockPayoutProvider is used; in prod nothing is sent (payouts stay accrued) until
a real provider integration (e.g. Wise payouts API) is built and wired into
`payout_provider()`. Real payouts need that integration before launch.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from arbiter.api.deps import DB, Admin, Paging, listing
from arbiter.api.routes.auth import org_view
from arbiter.billing.usage import current_period
from arbiter.community import disputes, payouts, profiles, testing
from arbiter.community.payouts import MockPayoutProvider, PayoutProvider
from arbiter.config import get_settings
from arbiter.models import Job, Organization, UsageRecord

router = APIRouter(prefix="/admin", tags=["admin"])


def payout_provider() -> PayoutProvider | None:
    """The provider that actually moves money. None = accrue only, send nothing.

    There is no real integration yet: production returns None so no payout is ever marked
    settled without money moving. Everything else uses the in-memory mock.
    """
    if get_settings().env == "prod":
        return None
    return MockPayoutProvider()


def _page(items: list[Any], pg: Any) -> dict[str, Any]:
    return listing(items[pg.offset : pg.offset + pg.limit + 1], pg)


# ------------------------------------------------------------------ reviewers


@router.get("/reviewers")
def list_reviewers(
    _: Admin,
    db: DB,
    pg: Paging,
    status: Literal["applied", "active", "suspended", "banned"] | None = Query(default=None),
) -> dict[str, Any]:
    return _page(profiles.list_profiles(db, status), pg)


class ReviewerStatusIn(BaseModel):
    status: Literal["applied", "active", "suspended", "banned"]
    level: Literal["candidate", "reviewer", "senior", "domain_expert"] | None = None


@router.post("/reviewers/{reviewer_id}/status")
def set_reviewer_status(reviewer_id: str, body: ReviewerStatusIn, _: Admin, db: DB) -> dict[str, Any]:
    return profiles.set_status(db, reviewer_id, body.status, body.level)


# ------------------------------------------------------------------ disputes


@router.get("/disputes")
def list_disputes(
    _: Admin,
    db: DB,
    pg: Paging,
    status: Literal["open", "upheld", "overturned", "expired"] | None = Query(default=None),
) -> dict[str, Any]:
    return _page(disputes.list_disputes(db, status), pg)


class DecideIn(BaseModel):
    outcome: Literal["upheld", "overturned"]
    note: str = Field(default="", max_length=5000)


@router.post("/disputes/{dispute_id}/decide")
def decide_dispute(dispute_id: str, body: DecideIn, p: Admin, db: DB) -> dict[str, Any]:
    assert p.user is not None
    return disputes.decide(db, dispute_id, body.outcome, body.note, p.user.id)


# ------------------------------------------------------------------ payouts


@router.get("/payouts")
def list_payouts(
    _: Admin,
    db: DB,
    pg: Paging,
    state: Literal["accrued", "blocked", "sent", "settled", "failed"] | None = Query(default=None),
) -> dict[str, Any]:
    return _page(payouts.list_payouts(db, state), pg)


@router.post("/payouts/run")
def run_payouts(_: Admin, db: DB) -> dict[str, Any]:
    provider = payout_provider()
    # run_payouts calls send_payouts itself when given a provider.
    out = payouts.run_payouts(db, provider=provider)
    out["provider"] = getattr(provider, "name", None) if provider is not None else None
    if provider is None:
        out["send"] = None
        out["note"] = "no payout provider configured: payouts were accrued, nothing was sent"
    return out


# ------------------------------------------------------------------ organizations


@router.get("/orgs")
def list_orgs(_: Admin, db: DB, pg: Paging) -> dict[str, Any]:
    """Every organization with usage for the current period (words metered, jobs created)."""
    period = current_period()
    orgs = list(
        db.execute(
            select(Organization)
            .order_by(Organization.created_at, Organization.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    ids = [o.id for o in orgs]
    words: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    jobs: dict[str, int] = defaultdict(int)
    if ids:
        for org_id, qty in db.execute(
            select(UsageRecord.org_id, func.sum(UsageRecord.quantity))
            .where(UsageRecord.org_id.in_(ids), UsageRecord.period == period, UsageRecord.unit == "word")
            .group_by(UsageRecord.org_id)
        ).all():
            words[org_id] = Decimal(qty or 0)
        year, month = (int(x) for x in period.split("-"))
        start = datetime(year, month, 1, tzinfo=UTC)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
        for org_id, n in db.execute(
            select(Job.org_id, func.count(Job.id))
            .where(Job.org_id.in_(ids), Job.created_at >= start, Job.created_at < end)
            .group_by(Job.org_id)
        ).all():
            jobs[org_id] = int(n)
    items = [
        {
            **org_view(o),
            "kind": o.kind,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "usage": {"period": period, "words": int(words[o.id]), "jobs": jobs[o.id]},
        }
        for o in orgs
    ]
    return listing(items, pg)


# ------------------------------------------------------------------ reviewer tests


class TestItemErrorIn(BaseModel):
    span: str = Field(max_length=2000)
    category: str = Field(max_length=60)
    severity: Literal["neutral", "minor", "major", "critical"]


class TestItemIn(BaseModel):
    source: str = Field(max_length=20_000)
    target: str = Field(max_length=20_000)
    errors: list[TestItemErrorIn] = Field(default_factory=list, max_length=20)
    reference: str | None = Field(default=None, max_length=20_000)


class ReviewerTestIn(BaseModel):
    kind: Literal["language", "practical"]
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    domain: str = Field(default="general", max_length=60)
    items: list[TestItemIn] = Field(min_length=1, max_length=200)
    pass_mark: float = Field(default=80.0, ge=0, le=100)
    time_limit_min: int = Field(default=45, ge=1, le=600)
    active: bool = True


@router.post("/tests", status_code=201)
def create_test(body: ReviewerTestIn, _: Admin, db: DB) -> dict[str, Any]:
    return testing.create_test(db, body.model_dump())

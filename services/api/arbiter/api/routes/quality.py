"""Quality dashboard for the customer: how much ships automatically and how much of it escaped.

auto_rate     = auto-approved segments / segments, over the org's jobs created in the window
escaped_rate  = accepted escaped errors on auto-approved segments / auto-approved segments
control_samples = blind checks of auto-approved segments in the window, by verdict
Rates are null when there is nothing to divide by: no data is not a 0% error rate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from arbiter.api.deps import DB, Customer, Paging, listing
from arbiter.models import ControlSample, EngineScore, EscapedError, Job, Threshold, utcnow

router = APIRouter(tags=["quality"])

WINDOW_DAYS = 30


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def threshold_view(t: Threshold) -> dict[str, Any]:
    return {
        "id": t.id,
        "content_type": t.content_type,
        "target_lang": t.target_lang,
        "value": t.value,
        "band_width": t.band_width,
        "safety_offset": t.safety_offset,
        "auto_approval_suspended": t.auto_approval_suspended,
        "suspended_reason": t.suspended_reason,
        "last_calibrated_at": _iso(t.last_calibrated_at),
    }


def _engine_view(e: EngineScore) -> dict[str, Any]:
    return {
        "engine": e.engine,
        "source_lang": e.source_lang,
        "target_lang": e.target_lang,
        "domain": e.domain,
        "segments_measured": e.segments_measured,
        "mean_qe": e.mean_qe,
        "mean_edit_distance": e.mean_edit_distance,
        "term_adherence": e.term_adherence,
        "updated_at": _iso(e.updated_at),
    }


@router.get("/quality/dashboard")
def dashboard(p: Customer, db: DB) -> dict[str, Any]:
    org_id = p.org_id
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    auto, total = db.execute(
        select(
            func.coalesce(func.sum(Job.auto_approved_count), 0),
            func.coalesce(func.sum(Job.segment_count), 0),
        ).where(Job.org_id == org_id, Job.created_at >= since, Job.segment_count > 0)
    ).one()
    auto, total = int(auto), int(total)
    escaped = db.execute(
        select(func.count())
        .select_from(EscapedError)
        .where(
            EscapedError.org_id == org_id,
            EscapedError.created_at >= since,
            EscapedError.was_auto_approved.is_(True),
            EscapedError.accepted.is_(True),
        )
    ).scalar_one()
    cs_rows = db.execute(
        select(ControlSample.verdict, func.count())
        .where(ControlSample.org_id == org_id, ControlSample.created_at >= since)
        .group_by(ControlSample.verdict)
    ).all()
    by_verdict = {v: int(n) for v, n in cs_rows}
    thresholds = db.execute(
        select(Threshold)
        .where(Threshold.org_id == org_id)
        .order_by(Threshold.content_type, Threshold.target_lang)
    ).scalars()
    # Engine scoreboard rows for the pairs this org actually uses (aggregate measurements).
    pairs = set(
        db.execute(select(Job.source_lang, Job.target_lang).where(Job.org_id == org_id).distinct()).all()
    )
    engines = []
    if pairs:
        for e in db.execute(
            select(EngineScore).order_by(EngineScore.source_lang, EngineScore.target_lang, EngineScore.engine)
        ).scalars():
            if (e.source_lang, e.target_lang) in pairs:
                engines.append(_engine_view(e))
    return {
        "window_days": WINDOW_DAYS,
        "segments": total,
        "auto_approved": auto,
        "auto_rate": round(auto / total, 4) if total else None,
        "escaped_errors": int(escaped),
        "escaped_rate": round(int(escaped) / auto, 4) if auto else None,
        "control_samples": {
            "total": sum(by_verdict.values()),
            "pending": by_verdict.get(None, 0),
            "ok": by_verdict.get("ok", 0),
            "escaped": by_verdict.get("escaped", 0),
        },
        "thresholds": [threshold_view(t) for t in thresholds],
        "engines": engines,
    }


@router.get("/quality/thresholds")
def thresholds(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(Threshold)
            .where(Threshold.org_id == p.org_id)
            .order_by(Threshold.content_type, Threshold.target_lang, Threshold.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([threshold_view(t) for t in rows], pg)

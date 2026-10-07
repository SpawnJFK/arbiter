"""Review task queue: creation, routing to reviewers, holds.

Routing (next_task):
  * the reviewer must be `active`, and the task's pair must be one of their `active` pairs
    (language codes match exactly or by primary subtag: pair "sr" serves "sr-latn")
  * reviewer level >= task.min_level   (candidate < reviewer < senior < domain_expert)
  * tasks the reviewer skipped are never offered to them again (task.expected["skipped_by"])
  * ordering: segments of a job they have not reviewed yet first, then domain match, then
    priority (minutes to the job deadline, lower = sooner), then age
  * rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED, so two reviewers asking at the
    same moment never get the same task
  * one held task per reviewer: asking again returns the task already held
Control tasks look exactly like real tasks to the reviewer (no flag in the payload).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, aliased

from arbiter.billing import ledger
from arbiter.community import pay
from arbiter.community.errors import Conflict, NotFound
from arbiter.community.transitions import move
from arbiter.models import Job, ReviewerPair, ReviewerProfile, ReviewTask, Segment, utcnow

LEVEL_ORDER = {"candidate": 0, "reviewer": 1, "senior": 2, "domain_expert": 3}
NO_DEADLINE_PRIORITY = 7 * 24 * 60  # a job without due_at sorts as if due in a week
DONE_STATES = ("submitted", "accepted", "rejected", "disputed", "payable")


def deadline_priority(due_at: datetime | None, now: datetime | None = None) -> int:
    """Minutes until the deadline, floored at 0 (overdue work goes first)."""
    if due_at is None:
        return NO_DEADLINE_PRIORITY
    now = now or utcnow()
    return max(0, int((due_at - now).total_seconds() // 60))


def create_task(
    session: Session,
    segment: Segment,
    job: Job,
    *,
    min_level: str = "reviewer",
    priority: int | None = None,
    is_control: bool = False,
    expected: dict[str, Any] | None = None,
) -> ReviewTask:
    """Queue one segment for human review. Called by the pipeline; flushes."""
    if min_level not in LEVEL_ORDER:
        raise ValueError(f"unknown level {min_level}")
    task = ReviewTask(
        segment_id=segment.id,
        job_id=job.id,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        domain=job.content_type or "general",
        min_level=min_level,
        priority=deadline_priority(job.due_at) if priority is None else priority,
        state="queued",
        is_control=is_control,
        expected=dict(expected) if expected is not None else None,
        target_before=segment.target_tagged,
        due_at=job.due_at,
    )
    session.add(task)
    session.flush()
    return task


def _lang_match(column: Any, lang: str) -> Any:
    lang = lang.lower()
    col = func.lower(column)
    return or_(col == lang, col.like(f"{lang}-%"))


def _covers(pair_lang: str, wanted: str | None) -> bool:
    if not wanted:
        return True
    p, w = pair_lang.lower(), wanted.lower()
    return p == w or w.startswith(p + "-") or p.startswith(w + "-")


def _active_pairs(
    session: Session, profile: ReviewerProfile, source_lang: str | None, target_lang: str | None
) -> list[ReviewerPair]:
    pairs = session.execute(
        select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id, ReviewerPair.status == "active")
    ).scalars()
    return [p for p in pairs if _covers(p.source_lang, source_lang) and _covers(p.target_lang, target_lang)]


def _held_by(session: Session, profile: ReviewerProfile) -> ReviewTask | None:
    return session.execute(
        select(ReviewTask)
        .where(ReviewTask.reviewer_id == profile.id, ReviewTask.state == "held")
        .order_by(ReviewTask.hold_expires_at.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()


def _requeue(task: ReviewTask) -> None:
    move(task, "task", "queued")
    task.reviewer_id = None
    task.hold_expires_at = None


def next_task(
    session: Session,
    profile: ReviewerProfile,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    hold_minutes: int = 10,
) -> dict[str, Any] | None:
    """POST /reviewer/tasks/next: the held task, or claim the best queued one. None = nothing."""
    if profile.status != "active":
        return None
    now = utcnow()
    held = _held_by(session, profile)
    if held is not None:
        if held.hold_expires_at is not None and held.hold_expires_at > now:
            return task_view(session, held, profile)
        _requeue(held)  # own hold expired: give it back before claiming again
        session.flush()

    pairs = _active_pairs(session, profile, source_lang, target_lang)
    if not pairs:
        return None
    level = LEVEL_ORDER.get(profile.level, 0)
    allowed_levels = [lv for lv, rank in LEVEL_ORDER.items() if rank <= level]
    pair_clause = or_(
        *[
            and_(
                _lang_match(ReviewTask.source_lang, p.source_lang),
                _lang_match(ReviewTask.target_lang, p.target_lang),
            )
            for p in pairs
        ]
    )
    skipped = func.coalesce(
        ReviewTask.expected.cast(JSONB)["skipped_by"].has_key(literal(profile.id)),  # noqa: W601
        false(),
    )
    mine = aliased(ReviewTask)
    reviewed_segments = select(mine.segment_id).where(
        mine.reviewer_id == profile.id, mine.state.in_(DONE_STATES)
    )
    seen_rank = case((ReviewTask.segment_id.in_(reviewed_segments), 1), else_=0)
    domains = [d for d in (profile.domains or []) if d]
    domain_rank = case((ReviewTask.domain.in_(domains), 0), else_=1) if domains else literal(0)

    stmt = (
        select(ReviewTask)
        .where(
            ReviewTask.state == "queued",
            ReviewTask.min_level.in_(allowed_levels),
            pair_clause,
            ~skipped,
            *([_lang_match(ReviewTask.source_lang, source_lang)] if source_lang else []),
            *([_lang_match(ReviewTask.target_lang, target_lang)] if target_lang else []),
        )
        .order_by(seen_rank, domain_rank, ReviewTask.priority, ReviewTask.created_at, ReviewTask.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = session.execute(stmt).scalar_one_or_none()
    if task is None:
        return None
    move(task, "task", "offered")
    move(task, "task", "held")
    task.reviewer_id = profile.id
    task.hold_expires_at = now + timedelta(minutes=hold_minutes)
    session.flush()
    return task_view(session, task, profile)


def _neighbour(session: Session, segment: Segment, offset: int) -> str | None:
    return session.execute(
        select(Segment.source_tagged).where(
            Segment.job_id == segment.job_id, Segment.seq == segment.seq + offset
        )
    ).scalar_one_or_none()


def segment_words(segment: Segment) -> int:
    if segment.word_count:
        return int(segment.word_count)
    return len((segment.source_plain or "").split())


def task_view(session: Session, task: ReviewTask, profile: ReviewerProfile) -> dict[str, Any]:
    """Task per docs/api-contract.md. Never reveals is_control or the expected answer."""
    segment = session.get(Segment, task.segment_id)
    if segment is None:
        raise NotFound("segment not found")
    signals = segment.signals or {}
    terms = [
        {"source_term": t.get("source_term"), "target_term": t.get("target_term"), "kind": t.get("kind")}
        for t in (signals.get("terms") or [])
        if isinstance(t, dict)
    ]
    words = segment_words(segment)
    return {
        "id": task.id,
        "segment_id": task.segment_id,
        "source_lang": task.source_lang,
        "target_lang": task.target_lang,
        "domain": task.domain,
        "source_tagged": segment.source_tagged,
        "target_tagged": task.target_before if task.target_before is not None else segment.target_tagged,
        "context_before": _neighbour(session, segment, -1),
        "context_after": _neighbour(session, segment, 1),
        "terms": terms,
        "qe_score": segment.qe_score,
        "flagged_errors": list(signals.get("errors") or []),
        "word_count": words,
        "hold_expires_at": task.hold_expires_at.isoformat() if task.hold_expires_at else None,
        "pay_estimate": ledger.money(pay.task_pay("accept", words, profile.level)),
        "pay_estimate_edit": ledger.money(pay.task_pay("edit", words, profile.level)),
    }


def release(session: Session, profile: ReviewerProfile, task_id: str) -> None:
    """POST /reviewer/tasks/{id}/release: give a held task back to the queue."""
    task = session.get(ReviewTask, task_id, with_for_update=True)
    if task is None or task.reviewer_id != profile.id:
        raise NotFound("task not found")
    if task.state != "held":
        raise Conflict(f"task is {task.state}, not held")
    _requeue(task)
    session.flush()


def expire_holds(session: Session, now: datetime | None = None) -> int:
    """Held tasks past hold_expires_at go back to queued. Returns how many."""
    now = now or utcnow()
    rows = session.execute(
        select(ReviewTask)
        .where(ReviewTask.state == "held", ReviewTask.hold_expires_at < now)
        .with_for_update(skip_locked=True)
    ).scalars()
    n = 0
    for task in rows:
        _requeue(task)
        n += 1
    session.flush()
    return n

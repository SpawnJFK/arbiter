"""Reviewer score (0..100), demotion and promotion.

Gengo-style: the score is driven by hidden control tasks with a known answer, not by
volume. Formula, computed from ReviewerScoreEvent rows (all, or one pair's):

    w(e)      = 0.5 ** (age_days(e) / HALF_LIFE_DAYS)          recency decay, half-life 90 days
    passes    = sum w(control_pass) + sum w(dispute_won)        an overturned fail counts as a pass
    fails     = max(0, sum w(control_fail) - sum w(dispute_won))
    accuracy  = (passes + PRIOR_ACCURACY * PRIOR_WEIGHT) / (passes + fails + PRIOR_WEIGHT)
                Bayesian prior: a new reviewer starts at 70 and needs ~10 controls to move far.
    penalty   = 3.0 * sum w(escaped)        error found later in a segment they approved
              + 1.0 * sum w(dispute_lost)   discourages frivolous disputes
              + 0.5 * sum w(speed_flag)     accept faster than ~0.6 s/word
    score     = clamp(100 * accuracy - penalty, 0, 100), rounded to 2 decimals

Rules applied after every event:
  * demotion  : a pair with score < 60 after >= 20 controls goes active -> demoted
  * promotion : level reviewer -> senior at score >= 90, >= 200 decisions and >= 50 controls
All constants are starting values; tune them once real control data exists.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import ReviewerPair, ReviewerProfile, ReviewerScoreEvent, ReviewTask, utcnow

PRIOR_ACCURACY = 0.70
PRIOR_WEIGHT = 10.0
HALF_LIFE_DAYS = 90.0
PENALTY = {"escaped": 3.0, "dispute_lost": 1.0, "speed_flag": 0.5}
DEMOTE_BELOW = 60.0
DEMOTE_MIN_CONTROLS = 20
PROMOTE_SCORE = 90.0
PROMOTE_MIN_DECISIONS = 200
PROMOTE_MIN_CONTROLS = 50
EVENT_KINDS = ("control_pass", "control_fail", "escaped", "dispute_won", "dispute_lost", "speed_flag")


def _weight(at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def compute(events: list[tuple[str, datetime]], now: datetime | None = None) -> float:
    """Score from (kind, created_at) pairs. Pure function, see module docstring."""
    now = now or utcnow()
    sums = dict.fromkeys(EVENT_KINDS, 0.0)
    for kind, at in events:
        if kind in sums:
            sums[kind] += _weight(at, now)
    passes = sums["control_pass"] + sums["dispute_won"]
    fails = max(0.0, sums["control_fail"] - sums["dispute_won"])
    accuracy = (passes + PRIOR_ACCURACY * PRIOR_WEIGHT) / (passes + fails + PRIOR_WEIGHT)
    penalty = sum(PENALTY[k] * sums[k] for k in PENALTY)
    return round(min(100.0, max(0.0, 100.0 * accuracy - penalty)), 2)


def _events(
    session: Session, reviewer_id: str, pair: ReviewerPair | None = None
) -> list[tuple[str, datetime]]:
    stmt = select(ReviewerScoreEvent.kind, ReviewerScoreEvent.created_at).where(
        ReviewerScoreEvent.reviewer_id == reviewer_id
    )
    if pair is not None:
        stmt = stmt.join(ReviewTask, ReviewTask.id == ReviewerScoreEvent.task_id).where(
            ReviewTask.source_lang == pair.source_lang, ReviewTask.target_lang == pair.target_lang
        )
    return [(k, at) for k, at in session.execute(stmt).all()]


def pair_for_task(session: Session, reviewer_id: str, task: ReviewTask | None) -> ReviewerPair | None:
    if task is None:
        return None
    pairs = (
        session.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == reviewer_id)).scalars().all()
    )
    src, tgt = task.source_lang.lower(), task.target_lang.lower()

    def match(a: str, b: str) -> bool:
        return a == b or a.startswith(b + "-") or b.startswith(a + "-")

    for p in pairs:
        if match(src, p.source_lang.lower()) and match(tgt, p.target_lang.lower()):
            return p
    return None


def recompute(session: Session, profile: ReviewerProfile, pair: ReviewerPair | None = None) -> float:
    """Recompute and store profile score (and pair score), then apply demotion/promotion."""
    session.flush()
    profile.score = compute(_events(session, profile.id))
    if pair is not None:
        pair.score = compute(_events(session, profile.id, pair))
        if pair.status == "active" and pair.control_seen >= DEMOTE_MIN_CONTROLS and pair.score < DEMOTE_BELOW:
            pair.status = "demoted"
    controls = sum(
        p.control_seen
        for p in session.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id)).scalars()
    )
    if (
        profile.level == "reviewer"
        and profile.score >= PROMOTE_SCORE
        and profile.decisions_total >= PROMOTE_MIN_DECISIONS
        and controls >= PROMOTE_MIN_CONTROLS
    ):
        profile.level = "senior"
    session.flush()
    return profile.score


def record_event(
    session: Session,
    profile: ReviewerProfile,
    kind: str,
    *,
    task: ReviewTask | None = None,
    note: str = "",
) -> ReviewerScoreEvent:
    """Append a score event and recompute. delta/score_after describe the profile score."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown score event kind {kind}")
    before = profile.score
    ev = ReviewerScoreEvent(
        reviewer_id=profile.id,
        task_id=task.id if task is not None else None,
        kind=kind,
        delta=0.0,
        score_after=before,
        note=note[:500],
    )
    session.add(ev)
    session.flush()
    after = recompute(session, profile, pair_for_task(session, profile.id, task))
    ev.delta = round(after - before, 2)
    ev.score_after = after
    session.flush()
    return ev


def record_escaped(
    session: Session, reviewer_id: str, task_id: str | None, note: str = ""
) -> ReviewerScoreEvent:
    """Called by the pipeline when an error is found in a segment this reviewer approved."""
    profile = session.get(ReviewerProfile, reviewer_id)
    if profile is None:
        raise ValueError("unknown reviewer")
    task = session.get(ReviewTask, task_id) if task_id else None
    return record_event(session, profile, "escaped", task=task, note=note)

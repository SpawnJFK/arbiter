"""Who does a job's human step (module pm): the marketplace, an own vendor or an internal user.

Route (per job and step, step = human_review | second_review):
  * marketplace   the default: no live assignment; the pipeline queues a review task per
                  segment for the reviewer community (unchanged behaviour)
  * vendor        the PM offers the step to one vendor or a ranked list
  * internal      the PM assigns a user of the org; accepted at once, no purchase order
A live assignment (status pending, offered, accepted, in_progress or delivered) takes the
step away from the marketplace: arbiter.pipeline.orchestrator._queue_review asks route_for()
and, when it gets an assignment, creates no review task (see the orchestrator docstring).

Offer flow (vendor):
  * sequential (default): rank 0 is offered, the rest wait as `pending`; a decline or the
    offer timeout (work item vendor.offer_timeout at offer_expires_at) offers the next rank
  * broadcast: everyone is offered at once; the first to accept wins
  * accepting withdraws every other offer of the group and issues the purchase order
    (arbiter.agency.procurement.issue_po)
  * when every vendor of the group declined or timed out, the step goes back to the
    marketplace (reroute) and the PM is told (webhook job.needs_attention, reason
    vendor_unassigned)
Each offer e-mails the vendor a no-login link to the vendor workbench (signed token, see
portal_token) through arbiter.notify; every message is also kept on the assignment
(messages).

Work: the vendor accepts or edits each open segment of the step in the workbench; every
decision goes through arbiter.pipeline.hooks.segment_reviewed, exactly like a marketplace
reviewer's. When no open segment of the step is left the assignment is `delivered`; the PM
approves it (cost added to job.cost_vendors, so the job margin includes it) or sends it back.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from arbiter.agency import vendors as vnd
from arbiter.agency.common import iso, money
from arbiter.agency.vendor_schemas import STEP_SERVICE, AssignmentIn, VendorSubmitIn
from arbiter.config import get_settings
from arbiter.domain.states import transition_status
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import (
    Job,
    Organization,
    PurchaseOrder,
    Segment,
    User,
    Vendor,
    VendorAssignment,
    new_id,
    utcnow,
)

log = logging.getLogger(__name__)

ROUTING = ("pending", "offered", "accepted", "in_progress", "delivered")
WORKING = ("accepted", "in_progress", "delivered", "approved", "invoiced")
ACTIVE_LOAD = ("accepted", "in_progress")
FINAL_JOB_STATES = ("delivered", "settled", "cancelled", "disputed")
TOKEN_AUDIENCE = "arbiter-vendor-portal"
TOKEN_DAYS_AFTER_DUE = 60


# --------------------------------------------------------------------------- lookups


def get_assignment(session: Session, org_id: str, asg_id: str, *, lock: bool = False) -> VendorAssignment:
    q = select(VendorAssignment).where(VendorAssignment.id == asg_id, VendorAssignment.org_id == org_id)
    if lock:
        q = q.with_for_update()
    a = session.execute(q).scalar_one_or_none()
    if a is None:
        raise NotFound("assignment not found")
    return a


def _group(session: Session, offer_group: str, *, lock: bool = False) -> list[VendorAssignment]:
    q = (
        select(VendorAssignment)
        .where(VendorAssignment.offer_group == offer_group)
        .order_by(VendorAssignment.rank, VendorAssignment.id)
    )
    if lock:
        q = q.with_for_update()
    return list(session.execute(q).scalars())


def live_assignments(session: Session, job_id: str, step: str) -> list[VendorAssignment]:
    return list(
        session.execute(
            select(VendorAssignment)
            .where(
                VendorAssignment.job_id == job_id,
                VendorAssignment.step == step,
                VendorAssignment.status.in_(ROUTING),
            )
            .order_by(VendorAssignment.created_at, VendorAssignment.rank)
        ).scalars()
    )


def route_for(session: Session, job: Job, step: str) -> VendorAssignment | None:
    """The assignment that holds (job, step), or None (the marketplace route).

    A working assignment (accepted, in progress, delivered) wins over open offers; a
    delivered assignment that gets new work is reopened by on_segment_routed()."""
    live = live_assignments(session, job.id, step)
    working = [a for a in live if a.status in ("accepted", "in_progress", "delivered")]
    if working:
        return working[0]
    offered = [a for a in live if a.status == "offered"]
    return (offered or live or [None])[0]


def on_segment_routed(session: Session, asg: VendorAssignment) -> None:
    """The pipeline handed a new segment to this assignment."""
    if asg.status == "delivered":
        transition_status(asg, "assignment", "in_progress")
        asg.delivered_at = None


def actor_id(asg: VendorAssignment) -> str:
    """The reviewer_id written on segments and provenance for this assignee."""
    return asg.vendor_id or asg.user_id or asg.id


# --------------------------------------------------------------------------- tokens


def portal_token(asg: VendorAssignment) -> str:
    """Signed, no-login link token for the vendor workbench. Rotating token_nonce revokes it."""
    s = get_settings()
    now = utcnow()
    until = max(asg.due_at or now, now) + timedelta(days=TOKEN_DAYS_AFTER_DUE)
    payload = {
        "aud": TOKEN_AUDIENCE,
        "asg": asg.id,
        "n": asg.token_nonce,
        "iat": int(now.timestamp()),
        "exp": int(until.timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def portal_link(asg: VendorAssignment) -> str:
    return f"{get_settings().web_base_url.rstrip('/')}/vendor/{portal_token(asg)}"


def from_token(session: Session, token: str, *, lock: bool = False) -> VendorAssignment:
    """The assignment a workbench token opens. Any bad, expired or revoked token is a 404."""
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=TOKEN_AUDIENCE)
    except jwt.PyJWTError:
        raise NotFound("this link is not valid or has expired") from None
    q = select(VendorAssignment).where(VendorAssignment.id == str(claims.get("asg")))
    if lock:
        q = q.with_for_update()
    asg = session.execute(q).scalar_one_or_none()
    if (
        asg is None
        or not asg.token_nonce
        or not secrets.compare_digest(asg.token_nonce, str(claims.get("n")))
    ):
        raise NotFound("this link is not valid or has expired")
    return asg


# --------------------------------------------------------------------------- create / change route


def _job_for_assignment(session: Session, org_id: str, job_id: str) -> Job:
    job = session.execute(
        select(Job).where(Job.id == job_id, Job.org_id == org_id).with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise NotFound("job not found")
    return job


def step_available(job: Job, step: str) -> bool:
    from arbiter.agency import workflows as wfl

    if step == "second_review":
        return wfl.has(job.workflow, "second_review")
    if job.workflow and wfl.has(job.workflow, "human_review"):
        return True
    # hybrid sends low scores to a human; full sends everything; a TM-only workflow sends
    # untranslated segments to a human whatever the tier
    return job.tier in ("hybrid", "full") or bool(job.workflow and not wfl.has(job.workflow, "mt"))


def step_words(session: Session, job: Job, step: str) -> int:
    """Words the step covers: the open segments of the step once the job is scored, else the
    whole job (the PM can override with `words`)."""
    from arbiter.pipeline import orchestrator

    if job.segment_count:
        segs = orchestrator.open_step_segments(session, job, step)
        if segs:
            return sum(s.word_count for s in segs)
    return job_words(session, job)


def job_words(session: Session, job: Job) -> int:
    """The job's words; before the job is prepared, the word count of its uploaded file."""
    from arbiter.models import FileAsset

    if job.word_count:
        return int(job.word_count)
    fa = session.get(FileAsset, job.file_id)
    return int(fa.word_count or 0) if fa else 0


def _release(session: Session, job: Job, step: str, *, keep: set[str] | None = None) -> None:
    """End every live assignment of (job, step) before a new route is set."""
    keep = keep or set()
    for a in live_assignments(session, job.id, step):
        if a.id in keep:
            continue
        if a.status == "delivered":
            raise Conflict(
                "this step was already delivered by the assignee; approve it or send it back first",
                {"assignment_id": a.id},
            )
        v = session.get(Vendor, a.vendor_id) if a.vendor_id else None
        to = v.email if v else None
        if a.status in ("pending", "offered"):
            was_offered = a.status == "offered"
            transition_status(a, "assignment", "withdrawn")
            if was_offered:
                _message_to(
                    a, to, "Offer withdrawn", "The job was assigned another way. No action is needed."
                )
        else:
            transition_status(a, "assignment", "cancelled")
            from arbiter.agency import procurement

            procurement.cancel_po_for(session, a)
            _message_to(a, to, "Assignment cancelled", "The project manager cancelled this assignment.")
        a.token_nonce = ""  # the old link stops working
        a.updated_at = utcnow()


def create(
    session: Session, org: Organization, job_id: str, body: AssignmentIn, user_id: str | None
) -> list[VendorAssignment]:
    """POST /jobs/{id}/assignments. Returns the new assignments ([] for the marketplace)."""
    from arbiter.pipeline import events, orchestrator

    job = _job_for_assignment(session, org.id, job_id)
    if job.state in FINAL_JOB_STATES or job.state == "failed":
        raise Conflict(f"the job is {job.state}; its human steps can no longer be assigned")
    if not step_available(job, body.step):
        raise Invalid(f"this job has no {body.step} step (tier {job.tier})")

    if body.mode == "marketplace":
        _release(session, job, body.step)
        session.flush()
        orchestrator.reroute_open_segments(session, job, body.step)
        events.record(
            session, job, "assignment_route", step=body.step, mode="marketplace", actor_id=user_id or ""
        )
        return []

    due_at = body.due_at or job.due_at
    words = body.words if body.words is not None else step_words(session, job, body.step)
    service = body.service or STEP_SERVICE[body.step]
    group = new_id("ofg")
    rows: list[VendorAssignment] = []

    if body.mode == "internal":
        user = session.get(User, body.user_id)
        if user is None or user.org_id != org.id or not user.is_active:
            raise NotFound("user not found")
        _release(session, job, body.step)
        a = VendorAssignment(
            org_id=org.id,
            job_id=job.id,
            step=body.step,
            service=service,
            assignee_kind="internal",
            user_id=user.id,
            offer_group=group,
            rank=0,
            strategy="sequential",
            words=words,
            unit="word",
            quantity=Decimal(words),
            rate=Decimal("0"),
            amount=Decimal("0"),
            currency=get_settings().currency,
            status="pending",
            due_at=due_at,
            offer_timeout_minutes=body.offer_timeout_minutes,
            token_nonce=secrets.token_urlsafe(24),
            note=body.note,
            messages=[],
            created_by=user_id,
        )
        session.add(a)
        session.flush()
        transition_status(a, "assignment", "offered")
        transition_status(a, "assignment", "accepted")
        a.offered_at = a.responded_at = utcnow()
        _message_to(a, user.email, "Job assigned to you", _offer_text(job, a), portal_link(a))
        rows.append(a)
    else:
        vendors = _vendors_for(session, org.id, job, body, service)
        _release(session, job, body.step)
        for rank, v in enumerate(vendors):
            amount, rate, unit, cur, quantity = _terms(v, job, body, service, words)
            a = VendorAssignment(
                org_id=org.id,
                job_id=job.id,
                step=body.step,
                service=service,
                assignee_kind="vendor",
                vendor_id=v.id,
                offer_group=group,
                rank=rank,
                strategy=body.strategy,
                words=words,
                unit=unit,
                quantity=quantity,
                rate=rate,
                amount=amount,
                currency=cur,
                status="pending",
                due_at=due_at,
                offer_timeout_minutes=body.offer_timeout_minutes,
                token_nonce=secrets.token_urlsafe(24),
                note=body.note,
                messages=[],
                created_by=user_id,
            )
            session.add(a)
            rows.append(a)
        session.flush()
        to_offer = rows if body.strategy == "broadcast" else rows[:1]
        for a in to_offer:
            _offer(session, a, job)
    session.flush()
    orchestrator.reroute_open_segments(session, job, body.step)
    events.record(
        session,
        job,
        "assignment_route",
        step=body.step,
        mode=body.mode,
        strategy=body.strategy,
        assignees=[a.vendor_id or a.user_id for a in rows],
        actor_id=user_id or "",
    )
    return rows


def _vendors_for(session: Session, org_id: str, job: Job, body: AssignmentIn, service: str) -> list[Vendor]:
    out: list[Vendor] = []
    excluded: set[str] = set()
    if body.step == "second_review":
        # four eyes: whoever did the first review never does the second one
        excluded = {
            a.vendor_id
            for a in session.execute(
                select(VendorAssignment).where(
                    VendorAssignment.job_id == job.id,
                    VendorAssignment.step == "human_review",
                    VendorAssignment.status.in_(WORKING),
                )
            ).scalars()
            if a.vendor_id
        }
    for vid in body.vendor_ids:
        v = vnd.get_vendor(session, org_id, vid)
        if v.status != "active":
            raise Invalid(f"vendor {v.name} is {v.status}", {"vendor_id": v.id})
        if not vnd.serves(v, job.source_lang, job.target_lang):
            raise Invalid(
                f"vendor {v.name} does not work in {job.source_lang}>{job.target_lang}", {"vendor_id": v.id}
            )
        if v.id in excluded:
            raise Invalid(
                f"vendor {v.name} did the first review of this job; the second review needs someone else",
                {"vendor_id": v.id},
            )
        out.append(v)
    return out


def _terms(
    v: Vendor, job: Job, body: AssignmentIn, service: str, words: int
) -> tuple[Decimal, Decimal, str, str, Decimal]:
    """(amount, rate, unit, currency, quantity) for one vendor. A rate in the body overrides."""
    if body.rate is not None:
        unit = body.unit or "word"
        quantity = body.quantity if body.quantity is not None else Decimal(words)
        amount = (body.rate * quantity).quantize(Decimal("0.01"))
        return amount, body.rate, unit, v.currency, quantity
    priced = vnd.price(v, job.source_lang, job.target_lang, service, words)
    if priced is None:
        raise Invalid(
            f"vendor {v.name} has no per-word {service} rate for {job.source_lang}>{job.target_lang}; "
            "add one to the vendor or give a rate",
            {"vendor_id": v.id},
        )
    amount, rate, unit, cur = priced
    return amount, rate, unit, cur, Decimal(words)


def _offer_text(job: Job, a: VendorAssignment) -> str:
    due = a.due_at.strftime("%Y-%m-%d %H:%M UTC") if a.due_at else "no fixed deadline"
    pay = f"{money(a.amount)} {a.currency}" if a.assignee_kind == "vendor" else "internal"
    return (
        f"{a.step.replace('_', ' ')} of {a.words} words, {job.source_lang} > {job.target_lang}, "
        f"due {due}. Fee: {pay}."
    )


def _message_to(
    a: VendorAssignment, to: str | None, subject: str, body: str, link: str | None = None
) -> None:
    session = object_session(a)
    name = ""
    if session is not None and a.vendor_id:
        v = session.get(Vendor, a.vendor_id)
        name = v.name if v else ""
    elif session is not None and a.user_id:
        u = session.get(User, a.user_id)
        name = (u.name or "") if u else ""
    record = vnd.notify(to, subject, body, link=link, session=session, org_id=a.org_id, name=name)
    a.messages = [*list(a.messages or []), record]


def _offer(session: Session, a: VendorAssignment, job: Job) -> None:
    from arbiter.pipeline.queue import enqueue

    transition_status(a, "assignment", "offered")
    now = utcnow()
    a.offered_at = now
    a.offer_expires_at = now + timedelta(minutes=a.offer_timeout_minutes)
    v = session.get(Vendor, a.vendor_id) if a.vendor_id else None
    _message_to(
        a,
        v.email if v else None,
        "New job offer",
        _offer_text(job, a) + " Open the link to accept or decline.",
        portal_link(a),
    )
    enqueue(
        session,
        "vendor.offer_timeout",
        {"assignment_id": a.id},
        run_at=a.offer_expires_at,
        idempotency_key=f"{a.id}:offer_timeout",
    )


def _advance_offer(session: Session, a: VendorAssignment) -> None:
    """After a decline or timeout: offer the next rank, or give the step back to the marketplace."""
    from arbiter import webhooks
    from arbiter.pipeline import events, orchestrator

    group = _group(session, a.offer_group, lock=True)
    if any(x.status in WORKING for x in group):
        return
    job = session.get(Job, a.job_id)
    assert job is not None
    if a.strategy == "sequential":
        nxt = next((x for x in group if x.status == "pending"), None)
        if nxt is not None:
            _offer(session, nxt, job)
            session.flush()
            orchestrator.reroute_open_segments(session, job, a.step)
            return
    if any(x.status == "offered" for x in group):
        return
    session.flush()
    orchestrator.reroute_open_segments(session, job, a.step)
    events.record(session, job, "vendor_offer_exhausted", step=a.step, offer_group=a.offer_group)
    webhooks.emit(
        session,
        job.org_id,
        "job.needs_attention",
        {"job_id": job.id, "reason": "vendor_unassigned", "step": a.step},
    )


# --------------------------------------------------------------------------- vendor responses


def accept(session: Session, a: VendorAssignment) -> VendorAssignment:
    from arbiter.agency import procurement
    from arbiter.pipeline import events

    group = _group(session, a.offer_group, lock=True)
    a = next(x for x in group if x.id == a.id)
    if a.status in WORKING:
        return a  # accepting twice is a no-op
    if any(x.status in WORKING for x in group):
        raise Conflict("another vendor already accepted this job")
    if a.status != "offered":
        raise Conflict(f"this offer is {a.status}")
    if a.offer_expires_at is not None and a.offer_expires_at < utcnow():
        raise Conflict("this offer has expired")
    transition_status(a, "assignment", "accepted")
    a.responded_at = utcnow()
    for x in group:
        if x.id != a.id and x.status in ("pending", "offered"):
            was_offered = x.status == "offered"
            transition_status(x, "assignment", "withdrawn")
            x.token_nonce = ""
            if was_offered:
                v = session.get(Vendor, x.vendor_id) if x.vendor_id else None
                _message_to(
                    x, v.email if v else None, "Offer taken", "Another linguist accepted this job first."
                )
    job = session.get(Job, a.job_id)
    assert job is not None
    session.flush()
    if a.assignee_kind == "vendor":
        procurement.issue_po(session, a)
    from arbiter.pipeline import orchestrator

    orchestrator.reroute_open_segments(session, job, a.step)
    events.record(session, job, "vendor_accepted", step=a.step, assignment_id=a.id, vendor_id=a.vendor_id)
    session.flush()
    return a


def decline(session: Session, a: VendorAssignment, reason: str = "") -> VendorAssignment:
    if a.status == "declined":
        return a
    if a.status != "offered":
        raise Conflict(f"this offer is {a.status}")
    transition_status(a, "assignment", "declined")
    a.responded_at = utcnow()
    a.note = (a.note + ("\n" if a.note else "") + f"Declined: {reason}".strip())[:5000] if reason else a.note
    session.flush()
    _advance_offer(session, a)
    return a


def offer_timeout(session: Session, payload: dict[str, Any]) -> None:
    """Work item vendor.offer_timeout: an unanswered offer expires and the next rank gets it."""
    a = session.execute(
        select(VendorAssignment).where(VendorAssignment.id == payload["assignment_id"]).with_for_update()
    ).scalar_one_or_none()
    if a is None or a.status != "offered":
        return
    if a.offer_expires_at is not None and a.offer_expires_at > utcnow():
        return  # the offer was renewed
    transition_status(a, "assignment", "expired")
    a.responded_at = utcnow()
    session.flush()
    _advance_offer(session, a)


HANDLERS = {"vendor.offer_timeout": offer_timeout}


# --------------------------------------------------------------------------- the work


def _clean_errors(errors: Any) -> list[dict[str, Any]]:
    out = []
    for e in errors or []:
        if not isinstance(e, dict):
            raise Invalid("every error must be an object")
        sev = e.get("severity", "minor")
        if sev not in ("neutral", "minor", "major", "critical"):
            raise Invalid("error severity must be one of neutral, minor, major, critical")
        out.append(
            {
                "dimension": str(e.get("dimension") or e.get("category") or "other")[:60],
                "severity": sev,
                "span": str(e.get("span") or "")[:500],
                "explanation": str(e.get("explanation") or "")[:2000],
            }
        )
    return out


def _check_tags(seg: Segment, target: str) -> None:
    """D-009: error-severity tag issues never ship (same rule as reviewers and customer edits)."""
    from arbiter.fileproc.base import TaggedParseError, from_tagged, validate_tags
    from arbiter.pipeline import orchestrator

    try:
        source = from_tagged(seg.source_tagged, orchestrator._codes(seg))  # noqa: SLF001
    except (TaggedParseError, ValueError):
        raise Invalid("the segment source cannot be parsed") from None
    issues = [i for i in validate_tags(source, target) if i.severity == "error"]
    if issues:
        raise Invalid(
            "the edited target breaks inline tags",
            {"tag_issues": [{"kind": i.kind, "code_id": i.code_id, "detail": i.detail} for i in issues]},
        )


def remaining(session: Session, a: VendorAssignment) -> list[Segment]:
    from arbiter.pipeline import orchestrator

    job = session.get(Job, a.job_id)
    assert job is not None
    return orchestrator.open_step_segments(session, job, a.step)


def _scoring_done(session: Session, job: Job) -> bool:
    from sqlalchemy import func

    if not job.segment_count:
        return False
    pending = session.execute(
        select(func.count())
        .select_from(Segment)
        .where(Segment.job_id == job.id, Segment.state.in_(("pending", "translated")))
    ).scalar_one()
    return pending == 0 and job.state in ("review", "ready", "merging", "delivered", "settled")


def submit_segment(
    session: Session, a: VendorAssignment, segment_id: str, body: VendorSubmitIn
) -> dict[str, Any]:
    """The assignee's decision on one segment, through the same hook as a marketplace reviewer."""
    from arbiter.pipeline import hooks

    if a.status not in ("accepted", "in_progress"):
        raise Conflict(
            f"this assignment is {a.status}"
            + (": ask the project manager to reopen it" if a.status == "delivered" else "")
        )
    job = session.get(Job, a.job_id)
    assert job is not None
    seg = session.execute(
        select(Segment).where(Segment.id == segment_id, Segment.job_id == job.id).with_for_update()
    ).scalar_one_or_none()
    if seg is None:
        raise NotFound("segment not found")
    if seg.id not in {s.id for s in remaining(session, a)} or (seg.signals or {}).get("route") != a.id:
        raise Conflict("this segment is not waiting for you")
    errors = _clean_errors(body.errors)
    if body.decision == "edit":
        if not body.target_tagged or not body.target_tagged.strip():
            raise Invalid("an edit needs target_tagged")
        _check_tags(seg, body.target_tagged)
        target = body.target_tagged
    else:
        target = seg.target_tagged or ""
    if a.status == "accepted":
        transition_status(a, "assignment", "in_progress")
        a.started_at = utcnow()
    a.words_done = int(a.words_done or 0) + int(seg.word_count or 0)
    hooks.segment_reviewed(
        session, seg.id, target_tagged=target, reviewer_id=actor_id(a), decision=body.decision, errors=errors
    )
    session.flush()
    left = remaining(session, a)
    mine = [s for s in left if (s.signals or {}).get("route") == a.id]
    if not mine and _scoring_done(session, job):
        _deliver(session, a, job)
    return {"ok": True, "remaining": len(mine), "status": a.status}


def _deliver(session: Session, a: VendorAssignment, job: Job) -> None:
    from arbiter import webhooks
    from arbiter.pipeline import events

    if a.status == "accepted":
        transition_status(a, "assignment", "in_progress")
    transition_status(a, "assignment", "delivered")
    a.delivered_at = utcnow()
    events.record(session, job, "vendor_delivered", step=a.step, assignment_id=a.id, actor_id=actor_id(a))
    webhooks.emit(
        session,
        job.org_id,
        "job.needs_attention",
        {"job_id": job.id, "reason": "vendor_delivered", "assignment_id": a.id},
    )


def complete(session: Session, a: VendorAssignment) -> VendorAssignment:
    """POST .../complete: the assignee says the step is done (only when nothing is left)."""
    if a.status == "delivered":
        return a
    if a.status not in ("accepted", "in_progress"):
        raise Conflict(f"this assignment is {a.status}")
    job = session.get(Job, a.job_id)
    assert job is not None
    if not _scoring_done(session, job):
        raise Conflict("the job is still being translated and scored; segments will appear here")
    left = [s for s in remaining(session, a) if (s.signals or {}).get("route") == a.id]
    if left:
        raise Conflict(f"{len(left)} segment(s) are still waiting for you")
    _deliver(session, a, job)
    session.flush()
    return a


# --------------------------------------------------------------------------- PM decisions


def approve(session: Session, a: VendorAssignment, user_id: str | None) -> VendorAssignment:
    """delivered -> approved; the vendor fee becomes job cost (margin includes vendor cost)."""
    from arbiter.pipeline import events

    if a.status in ("approved", "invoiced"):
        return a
    if a.status != "delivered":
        raise Conflict(f"only delivered work can be approved (this assignment is {a.status})")
    transition_status(a, "assignment", "approved")
    a.approved_at = utcnow()
    job = session.execute(select(Job).where(Job.id == a.job_id).with_for_update()).scalar_one()
    if a.assignee_kind == "vendor" and a.amount:
        if a.currency == get_settings().currency:
            job.cost_vendors = Decimal(job.cost_vendors or 0) + Decimal(a.amount)
        else:
            # Job money is kept in the platform currency; a foreign-currency fee is not
            # converted silently. It stays on the PO / vendor invoice and is flagged here.
            events.record(
                session,
                job,
                "vendor_cost_foreign_currency",
                assignment_id=a.id,
                amount=money(a.amount),
                currency=a.currency,
            )
    events.record(
        session,
        job,
        "vendor_approved",
        assignment_id=a.id,
        amount=money(a.amount),
        currency=a.currency,
        actor_type="human",
        actor_id=user_id or "",
    )
    session.flush()
    return a


def reopen(session: Session, a: VendorAssignment, note: str = "") -> VendorAssignment:
    if a.status != "delivered":
        raise Conflict(f"only delivered work can be sent back (this assignment is {a.status})")
    transition_status(a, "assignment", "in_progress")
    a.delivered_at = None
    if note:
        a.note = (a.note + "\n" + f"Sent back: {note}").strip()[:5000]
    v = session.get(Vendor, a.vendor_id) if a.vendor_id else None
    _message_to(
        a,
        v.email if v else None,
        "Work sent back",
        note or "The project manager reopened the job.",
        portal_link(a),
    )
    session.flush()
    return a


def cancel(session: Session, a: VendorAssignment) -> VendorAssignment:
    """PM cancels an assignment; the step goes back to the marketplace unless another is live."""
    from arbiter.pipeline import orchestrator

    job = session.execute(select(Job).where(Job.id == a.job_id).with_for_update()).scalar_one()
    if a.status in ("pending", "offered"):
        for x in _group(session, a.offer_group, lock=True):
            if x.status in ("pending", "offered"):
                transition_status(x, "assignment", "withdrawn")
                x.token_nonce = ""
    elif a.status in ("accepted", "in_progress"):
        from arbiter.agency import procurement

        transition_status(a, "assignment", "cancelled")
        a.token_nonce = ""
        procurement.cancel_po_for(session, a)
    else:
        raise Conflict(f"an assignment that is {a.status} cannot be cancelled")
    session.flush()
    orchestrator.reroute_open_segments(session, job, a.step)
    return a


# --------------------------------------------------------------------------- views


def assignment_view(session: Session, a: VendorAssignment, *, with_link: bool = False) -> dict[str, Any]:
    v = session.get(Vendor, a.vendor_id) if a.vendor_id else None
    u = session.get(User, a.user_id) if a.user_id else None
    po = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
    ).scalar_one_or_none()
    out: dict[str, Any] = {
        "id": a.id,
        "job_id": a.job_id,
        "step": a.step,
        "service": a.service,
        "assignee_kind": a.assignee_kind,
        "vendor_id": a.vendor_id,
        "vendor_name": v.name if v else None,
        "user_id": a.user_id,
        "user_name": (u.name or u.email) if u else None,
        "offer_group": a.offer_group,
        "rank": a.rank,
        "strategy": a.strategy,
        "words": a.words,
        "words_done": a.words_done,
        "unit": a.unit,
        "quantity": str(a.quantity),
        "rate": str(Decimal(a.rate).normalize()),
        "amount": money(a.amount),
        "currency": a.currency,
        "status": a.status,
        "due_at": iso(a.due_at),
        "offered_at": iso(a.offered_at),
        "offer_expires_at": iso(a.offer_expires_at),
        "responded_at": iso(a.responded_at),
        "started_at": iso(a.started_at),
        "delivered_at": iso(a.delivered_at),
        "approved_at": iso(a.approved_at),
        "po_id": po.id if po else None,
        "po_number": po.number if po else None,
        "note": a.note,
        "messages": list(a.messages or []),
        "created_at": iso(a.created_at),
    }
    if with_link and a.token_nonce and a.status in ROUTING:
        out["link"] = portal_link(a)
    return out


def _neighbour(session: Session, seg: Segment, offset: int) -> str | None:
    return session.execute(
        select(Segment.source_tagged).where(Segment.job_id == seg.job_id, Segment.seq == seg.seq + offset)
    ).scalar_one_or_none()


def _segment_payload(session: Session, seg: Segment, done: bool) -> dict[str, Any]:
    signals = seg.signals or {}
    return {
        "id": seg.id,
        "seq": seg.seq,
        "source_tagged": seg.source_tagged,
        "target_tagged": seg.target_tagged,
        "context_before": _neighbour(session, seg, -1),
        "context_after": _neighbour(session, seg, 1),
        "terms": [
            {"source_term": t.get("source_term"), "target_term": t.get("target_term"), "kind": t.get("kind")}
            for t in (signals.get("term_violations") or [])
            if isinstance(t, dict)
        ],
        "qe_score": seg.qe_score,
        "flagged_errors": list(signals.get("errors") or []),
        "word_count": seg.word_count,
        "state": seg.state,
        "done": done,
    }


def portal_view(session: Session, a: VendorAssignment) -> dict[str, Any]:
    """What the vendor workbench shows. No other vendor, no client money, no margin."""
    job = session.get(Job, a.job_id)
    assert job is not None
    org = session.get(Organization, a.org_id)
    po = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
    ).scalar_one_or_none()
    out: dict[str, Any] = {
        "assignment": {
            "id": a.id,
            "step": a.step,
            "service": a.service,
            "assignee_kind": a.assignee_kind,
            "status": a.status,
            "words": a.words,
            "words_done": a.words_done,
            "rate": str(Decimal(a.rate).normalize()),
            "unit": a.unit,
            "amount": money(a.amount),
            "currency": a.currency,
            "due_at": iso(a.due_at),
            "offer_expires_at": iso(a.offer_expires_at),
            "note": a.note,
            "po_number": po.number if po else None,
        },
        "organization": org.name if org else "",
        "job": {
            "id": job.id,
            "source_lang": job.source_lang,
            "target_lang": job.target_lang,
            "content_type": job.content_type,
            "state": job.state,
            "segment_count": job.segment_count,
        },
        "segments": [],
        "remaining": 0,
    }
    if a.status in WORKING:
        actor = actor_id(a)
        todo = [s for s in remaining(session, a) if (s.signals or {}).get("route") == a.id]
        done_rows = list(
            session.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars()
        )
        done = [
            s
            for s in done_rows
            if any(r.get("reviewer_id") == actor for r in ((s.signals or {}).get("reviews") or []))
            and s.id not in {t.id for t in todo}
        ]
        segs = sorted([(s, False) for s in todo] + [(s, True) for s in done], key=lambda x: x[0].seq)
        out["segments"] = [_segment_payload(session, s, d) for s, d in segs]
        out["remaining"] = len(todo)
    return out

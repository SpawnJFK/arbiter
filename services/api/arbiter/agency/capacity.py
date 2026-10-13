"""Capacity planning and deadline risk (module pm).

Vendor capacity per calendar day (UTC dates):
  capacity(day) = vendor.capacity_words_per_day on a working day (vendor.working_days) that
                  is not inside an absence, else 0
  load(day)     = the remaining words (words - words_done) of the vendor's accepted and
                  in-progress assignments, spread evenly over the vendor's working days from
                  today to the assignment's due date; without a due date (or when it already
                  passed) the work is booked from today at full capacity, first come first served
  free(day)     = max(0, capacity - load)

planner(): who can take N words of pair X by a date. For each active vendor serving the
pair: free words until the date, the earliest date N words fit, the price (vendor rate), and
can_meet. Sorted by can_meet, earliest finish, price, rating.

deadline_risk(): for every running or in-review job with a due date still ahead, the human
words left per step (needs_review segments, plus not yet scored segments times the share
expected to need a human: all on `full`, 1 - est_auto_rate (0.5 without history) on
`hybrid`), divided by the capacity of the step's route:
  vendor       the vendor's free capacity (its own assignment excluded from the load)
  internal     org.settings["pm"]["internal_words_per_day"] (default 4000) on weekdays
  marketplace  org.settings["pm"]["marketplace_words_per_day"] (default 20000) every day;
               an assumption about community throughput, not a promise
estimated_finish = the latest step finish; at risk when it is after due_at. An offer not yet
accepted within 24 hours of the deadline is a risk too. These are estimates for a PM's eyes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.agency import vendors as vnd
from arbiter.agency.common import iso, money
from arbiter.models import (
    Job,
    Organization,
    Project,
    Segment,
    Vendor,
    VendorAbsence,
    VendorAssignment,
    utcnow,
)

HORIZON_DAYS = 180
LOAD_STATUSES = ("accepted", "in_progress")
DEFAULT_MARKETPLACE_WPD = 20_000
DEFAULT_INTERNAL_WPD = 4_000
DEFAULT_AUTO_SHARE = 0.5


def _end_of(d: date) -> datetime:
    return datetime.combine(d, time(23, 59), tzinfo=UTC)


class VendorCalendar:
    """Capacity, load and absences of one vendor, day by day."""

    def __init__(
        self,
        vendor: Vendor,
        absences: list[VendorAbsence],
        assignments: list[VendorAssignment],
        today: date,
        *,
        exclude_assignment: str | None = None,
    ) -> None:
        self.vendor = vendor
        self.today = today
        self.absent: set[date] = set()
        for a in absences:
            d = max(a.start_date, today)
            while d <= a.end_date and d <= today + timedelta(days=HORIZON_DAYS):
                self.absent.add(d)
                d += timedelta(days=1)
        self.load: dict[date, float] = defaultdict(float)
        self.assignments_by_day: dict[date, list[str]] = defaultdict(list)
        for asg in sorted(assignments, key=lambda x: (x.due_at is None, x.due_at or utcnow())):
            if asg.id == exclude_assignment or asg.status not in LOAD_STATUSES:
                continue
            self._book(asg)

    def working(self, d: date) -> bool:
        return d.weekday() in (self.vendor.working_days or []) and d not in self.absent

    def capacity(self, d: date) -> int:
        return int(self.vendor.capacity_words_per_day or 0) if self.working(d) else 0

    def free(self, d: date) -> int:
        return max(0, int(self.capacity(d) - self.load.get(d, 0.0)))

    def _book(self, asg: VendorAssignment) -> None:
        left = float(max(0, int(asg.words or 0) - int(asg.words_done or 0)))
        if left <= 0:
            return
        due = asg.due_at.date() if asg.due_at else None
        days: list[date] = []
        if due is not None and due >= self.today:
            d = self.today
            while d <= due:
                if self.working(d):
                    days.append(d)
                d += timedelta(days=1)
        if days:
            share = left / len(days)
            for d in days:
                self.load[d] += share
                self.assignments_by_day[d].append(asg.id)
            return
        d = self.today
        for _ in range(HORIZON_DAYS):
            room = self.capacity(d) - self.load.get(d, 0.0)
            if room > 0:
                take = min(room, left)
                self.load[d] += take
                self.assignments_by_day[d].append(asg.id)
                left -= take
                if left <= 0:
                    return
            d += timedelta(days=1)

    def free_until(self, end: date) -> int:
        total, d = 0, self.today
        while d <= end:
            total += self.free(d)
            d += timedelta(days=1)
        return total

    def finish_date(self, words: int, start: date | None = None) -> date | None:
        """First day by which `words` fit into the free capacity, or None within the horizon."""
        if words <= 0:
            return start or self.today
        acc, d = 0, start or self.today
        for _ in range(HORIZON_DAYS):
            acc += self.free(d)
            if acc >= words:
                return d
            d += timedelta(days=1)
        return None


def _calendars(
    session: Session, org_id: str, vendors: list[Vendor], today: date, exclude: str | None = None
) -> dict[str, VendorCalendar]:
    ids = [v.id for v in vendors]
    if not ids:
        return {}
    absences: dict[str, list[VendorAbsence]] = defaultdict(list)
    for a in session.execute(
        select(VendorAbsence).where(
            VendorAbsence.org_id == org_id, VendorAbsence.vendor_id.in_(ids), VendorAbsence.end_date >= today
        )
    ).scalars():
        absences[a.vendor_id].append(a)
    loads: dict[str, list[VendorAssignment]] = defaultdict(list)
    for a in session.execute(
        select(VendorAssignment).where(
            VendorAssignment.org_id == org_id,
            VendorAssignment.vendor_id.in_(ids),
            VendorAssignment.status.in_(LOAD_STATUSES),
        )
    ).scalars():
        assert a.vendor_id is not None
        loads[a.vendor_id].append(a)
    return {
        v.id: VendorCalendar(v, absences[v.id], loads[v.id], today, exclude_assignment=exclude)
        for v in vendors
    }


def _vendors(session: Session, org_id: str, *, active_only: bool = True) -> list[Vendor]:
    q = select(Vendor).where(Vendor.org_id == org_id)
    if active_only:
        q = q.where(Vendor.status == "active")
    return list(session.execute(q.order_by(Vendor.name, Vendor.id)).scalars())


# --------------------------------------------------------------------------- planner


def planner(
    session: Session,
    org_id: str,
    *,
    source_lang: str,
    target_lang: str,
    words: int,
    by: date | None = None,
    service: str | None = None,
    exclude_vendor_ids: set[str] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or utcnow().date()
    exclude_vendor_ids = exclude_vendor_ids or set()
    candidates = [v for v in _vendors(session, org_id) if vnd.serves(v, source_lang, target_lang, service)]
    cals = _calendars(session, org_id, candidates, today)
    rows: list[dict[str, Any]] = []
    for v in candidates:
        cal = cals[v.id]
        end = by or (today + timedelta(days=30))
        finish = cal.finish_date(words)
        priced = vnd.price(v, source_lang, target_lang, service or "translation", words)
        absent_days = sorted(d for d in cal.absent if today <= d <= end)
        rows.append(
            {
                "vendor_id": v.id,
                "name": v.name,
                "kind": v.kind,
                "email": v.email,
                "capacity_words_per_day": v.capacity_words_per_day,
                "free_words": cal.free_until(end) if end >= today else 0,
                "earliest_finish": iso(finish),
                "can_meet": bool(finish is not None and (by is None or finish <= by)),
                "absent_days": [iso(d) for d in absent_days],
                "price": (
                    {
                        "amount": money(priced[0]),
                        "rate": str(priced[1].normalize()),
                        "unit": priced[2],
                        "currency": priced[3],
                    }
                    if priced
                    else None
                ),
                "rating": str(Decimal(v.rating).quantize(Decimal("0.01"))) if v.rating is not None else None,
                "nda_signed": v.nda_signed,
                "eligible": v.id not in exclude_vendor_ids,
            }
        )

    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        amount = Decimal(r["price"]["amount"]) if r["price"] else Decimal("1e12")
        rating = Decimal(r["rating"]) if r["rating"] else Decimal("0")
        return (
            not r["eligible"],
            not r["can_meet"],
            r["earliest_finish"] is None,
            r["earliest_finish"] or "",
            amount,
            -rating,
            r["name"].lower(),
        )

    rows.sort(key=key)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def suggestions_for_job(session: Session, job: Job, step: str) -> dict[str, Any]:
    """Ranked vendors for a job's step, with price and availability (assignment picker)."""
    from arbiter.agency import assignments
    from arbiter.agency.vendor_schemas import STEP_SERVICE

    words = assignments.step_words(session, job, step)
    exclude: set[str] = set()
    if step == "second_review":
        exclude = {
            a.vendor_id
            for a in session.execute(
                select(VendorAssignment).where(
                    VendorAssignment.job_id == job.id,
                    VendorAssignment.step == "human_review",
                    VendorAssignment.status.in_(assignments.WORKING),
                )
            ).scalars()
            if a.vendor_id
        }
    rows = planner(
        session,
        job.org_id,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        words=words,
        by=job.due_at.date() if job.due_at else None,
        service=STEP_SERVICE[step],
        exclude_vendor_ids=exclude,
    )
    return {"job_id": job.id, "step": step, "words": words, "due_at": iso(job.due_at), "items": rows}


# --------------------------------------------------------------------------- deadline risk


def _pm_setting(org: Organization | None, key: str, default: int) -> int:
    try:
        return int(((org.settings or {}).get("pm") or {}).get(key, default)) if org else default
    except (TypeError, ValueError):
        return default


def _step_words(session: Session, job: Job) -> dict[str, int]:
    from arbiter.agency import workflows as wfl
    from arbiter.pipeline import orchestrator

    segs = list(
        session.execute(
            select(Segment).where(
                Segment.job_id == job.id,
                Segment.state.in_(("pending", "translated", "needs_review", "in_review")),
            )
        ).scalars()
    )
    second = wfl.has(job.workflow, "second_review")
    share = (
        1.0
        if job.tier == "full"
        else (1.0 - (job.est_auto_rate if job.est_auto_rate is not None else DEFAULT_AUTO_SHARE))
        if job.tier == "hybrid"
        else 0.0
    )
    out = {"human_review": 0, "second_review": 0}
    if not segs and not job.segment_count:
        # not prepared yet: the whole job, by the same expectation
        from arbiter.agency.assignments import job_words

        expected = int(round(job_words(session, job) * share))
        out["human_review"] = expected
        if second:
            out["second_review"] = expected
        return out
    for s in segs:
        if s.is_control_sample:
            continue
        if s.state in ("pending", "translated"):
            expected = int(round(s.word_count * share))
            out["human_review"] += expected
            if second:
                out["second_review"] += expected
            continue
        step = orchestrator.segment_step(job, s)
        out[step] += s.word_count
        if step == "human_review" and second:
            out["second_review"] += s.word_count
    return out


def job_risk(session: Session, job: Job, now: datetime | None = None) -> dict[str, Any] | None:
    from arbiter.agency import assignments

    now = now or utcnow()
    if job.due_at is None or job.state not in ("running", "review"):
        return None
    org = session.get(Organization, job.org_id)
    words = _step_words(session, job)
    finishes: list[datetime] = []
    routes: dict[str, Any] = {}
    reasons: list[str] = []
    for step, n in words.items():
        if n <= 0:
            continue
        asg = assignments.route_for(session, job, step)
        if asg is None:
            wpd = _pm_setting(org, "marketplace_words_per_day", DEFAULT_MARKETPLACE_WPD)
            finish = now + timedelta(days=n / max(wpd, 1))
            routes[step] = {"route": "marketplace", "words": n, "words_per_day": wpd}
        elif asg.assignee_kind == "internal":
            wpd = _pm_setting(org, "internal_words_per_day", DEFAULT_INTERNAL_WPD)
            d, acc = now.date(), 0
            for _ in range(HORIZON_DAYS):
                acc += wpd if d.weekday() < 5 else 0
                if acc >= n:
                    break
                d += timedelta(days=1)
            finish = _end_of(d)
            routes[step] = {"route": "internal", "words": n, "words_per_day": wpd, "assignment_id": asg.id}
        else:
            v = session.get(Vendor, asg.vendor_id)
            assert v is not None
            cal = _calendars(session, job.org_id, [v], now.date(), exclude=asg.id)[v.id]
            fd = cal.finish_date(n)
            finish = _end_of(fd) if fd is not None else now + timedelta(days=HORIZON_DAYS)
            routes[step] = {
                "route": "vendor",
                "words": n,
                "words_per_day": v.capacity_words_per_day,
                "assignment_id": asg.id,
                "vendor_id": v.id,
                "vendor_name": v.name,
                "status": asg.status,
            }
            if asg.status in ("pending", "offered") and job.due_at - now < timedelta(hours=24):
                reasons.append(f"the {step.replace('_', ' ')} offer is not accepted yet")
        finishes.append(finish)
    if not finishes:
        return None
    est = max(finishes)
    if est > job.due_at:
        reasons.insert(0, "estimated finish is after the due date")
    remaining = sum(words.values())
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "source_lang": job.source_lang,
        "target_lang": job.target_lang,
        "state": job.state,
        "due_at": iso(job.due_at),
        "remaining_words": remaining,
        "estimated_finish": iso(est),
        "slack_hours": round((job.due_at - est).total_seconds() / 3600, 1),
        "routes": routes,
        "at_risk": bool(reasons),
        "reasons": reasons,
    }


def deadline_risk(session: Session, org_id: str, *, only_at_risk: bool = False) -> list[dict[str, Any]]:
    now = utcnow()
    jobs = list(
        session.execute(
            select(Job)
            .where(
                Job.org_id == org_id,
                Job.state.in_(("running", "review")),
                Job.due_at.is_not(None),
                Job.due_at > now,
            )
            .order_by(Job.due_at, Job.id)
        ).scalars()
    )
    names = (
        dict(
            session.execute(
                select(Project.id, Project.name).where(Project.id.in_({j.project_id for j in jobs}))
            ).all()
        )
        if jobs
        else {}
    )
    out = []
    for j in jobs:
        r = job_risk(session, j, now)
        if r is None or (only_at_risk and not r["at_risk"]):
            continue
        r["project"] = names.get(j.project_id)
        out.append(r)
    return out


# --------------------------------------------------------------------------- timeline


def timeline(session: Session, org_id: str, start: date, days: int) -> dict[str, Any]:
    """Per vendor and day: capacity, load, free, absences and the assignments booked; plus the
    jobs due in the window (calendar view)."""
    days = max(1, min(days, 62))
    end = start + timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    vendors = _vendors(session, org_id)
    cals = _calendars(session, org_id, vendors, min(start, utcnow().date()))
    asgs = list(
        session.execute(
            select(VendorAssignment).where(
                VendorAssignment.org_id == org_id,
                VendorAssignment.status.in_(("offered", "accepted", "in_progress", "delivered")),
            )
        ).scalars()
    )
    rows = []
    for v in vendors:
        cal = cals[v.id]
        rows.append(
            {
                "vendor_id": v.id,
                "name": v.name,
                "capacity_words_per_day": v.capacity_words_per_day,
                "days": [
                    {
                        "date": iso(d),
                        "capacity": cal.capacity(d),
                        "load": int(round(cal.load.get(d, 0.0))),
                        "free": cal.free(d),
                        "absent": d in cal.absent,
                        "working": d.weekday() in (v.working_days or []),
                        "assignments": cal.assignments_by_day.get(d, []),
                    }
                    for d in dates
                ],
            }
        )
    jobs = list(
        session.execute(
            select(Job, Project.name)
            .join(Project, Project.id == Job.project_id)
            .where(
                Job.org_id == org_id,
                Job.due_at.is_not(None),
                Job.due_at >= _end_of(start) - timedelta(days=1),
                Job.due_at <= _end_of(end),
            )
            .order_by(Job.due_at)
        ).all()
    )
    risk = {r["job_id"]: r for r in deadline_risk(session, org_id)}
    return {
        "start": iso(start),
        "days": [iso(d) for d in dates],
        "vendors": rows,
        "assignments": [
            {
                "id": a.id,
                "vendor_id": a.vendor_id,
                "user_id": a.user_id,
                "job_id": a.job_id,
                "step": a.step,
                "status": a.status,
                "words": a.words,
                "words_done": a.words_done,
                "start": iso((a.started_at or a.responded_at or a.offered_at or a.created_at).date()),
                "due_at": iso(a.due_at),
            }
            for a in asgs
        ],
        "jobs": [
            {
                "job_id": j.id,
                "project": name,
                "state": j.state,
                "due_at": iso(j.due_at),
                "source_lang": j.source_lang,
                "target_lang": j.target_lang,
                "at_risk": bool(risk.get(j.id, {}).get("at_risk")),
            }
            for j, name in jobs
        ],
    }

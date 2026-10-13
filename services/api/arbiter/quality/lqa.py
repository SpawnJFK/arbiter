"""Job LQA (module ai): an MQM scorecard per job from the errors humans and the senate found.

Sources, per segment:
- reviewer errors: ReviewTask.errors of submitted or accepted (or payable) tasks; a
  rejected review's errors do not count
- senate confirmed errors: SenateRun.confirmed of review senates (purpose "review")
Identical findings (same segment, dimension and span) from both sources count once, at the
higher severity, so a reviewer confirming the senate is not a double penalty. The
evaluation word count is the job's source word count.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.contracts import SEVERITY_WEIGHT
from arbiter.models import Job, Organization, ReviewTask, Segment, SenateRun
from arbiter.quality import scorecard

COUNTED_TASK_STATES = ("submitted", "accepted", "payable")


def job_errors(session: Session, job: Job) -> list[dict[str, Any]]:
    segs = {s.id: s for s in session.execute(select(Segment).where(Segment.job_id == job.id)).scalars()}
    found: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(seg_id: str, raw: dict[str, Any], source: str) -> None:
        row = scorecard.normalize_error(raw, source)
        seg = segs.get(seg_id)
        if row is None or seg is None:
            return
        key = (seg_id, row["dimension"], row["span"].strip().lower())
        row = {
            **row,
            "segment_id": seg_id,
            "seq": seg.seq + 1,
            "source_text": seg.source_plain,
            "target_text": seg.target_tagged or "",
        }
        prev = found.get(key)
        if prev is None:
            found[key] = row
        elif SEVERITY_WEIGHT[row["severity"]] > SEVERITY_WEIGHT[prev["severity"]]:
            found[key] = {**row, "source": f"{prev['source']}+{source}"}
        elif source not in prev["source"]:
            prev["source"] = f"{prev['source']}+{source}"

    for task in session.execute(
        select(ReviewTask).where(
            ReviewTask.job_id == job.id,
            ReviewTask.state.in_(COUNTED_TASK_STATES),
            ReviewTask.is_control.is_(False),
        )
    ).scalars():
        for e in task.errors or []:
            add(task.segment_id, e, "reviewer")
    for run in session.execute(
        select(SenateRun).where(SenateRun.job_id == job.id, SenateRun.purpose == "review")
    ).scalars():
        for e in run.confirmed or []:
            add(run.segment_id, e, "senate")
    return sorted(found.values(), key=lambda r: (r["seq"], -SEVERITY_WEIGHT[r["severity"]]))


def job_scorecard(session: Session, job: Job) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    org = session.get(Organization, job.org_id)
    settings = scorecard.settings_for(org)
    rows = job_errors(session, job)
    card = scorecard.scorecard(rows, job.word_count or 0, settings)
    card["job_id"] = job.id
    card["segments_with_errors"] = len({r["segment_id"] for r in rows})
    card["sources"] = {
        "reviewer": sum(1 for r in rows if "reviewer" in r["source"]),
        "senate": sum(1 for r in rows if "senate" in r["source"]),
    }
    return card, rows


def meta_lines(job: Job, filename: str | None) -> list[str]:
    return [
        f"Job {job.id} · {filename or ''} · {job.source_lang} to {job.target_lang} · tier {job.tier}",
        f"Content type {job.content_type} · state {job.state} · {job.word_count} source words",
    ]

"""Human review of string translations through the existing reviewer community (D-052).

Review tasks reference a segment of a job (review_tasks.segment_id is a foreign key), and the
whole community flow (routing by language pair and level, holds, pay, control grading,
disputes) is built on that. Instead of a second task type, strings use a small adapter:

  * one carrier Project + FileAsset (format "strings", no file) per string project, created on
    first use, and one carrier Job per (string project, target language) while it has open
    review work. The job's workflow snapshot is {"adapter": "strings", ...} with no steps, so
    the pipeline's workflow checks see nothing and no pipeline step is ever enqueued for it;
  * one Segment per translation and form (unit_id "strtr:<translation id>:<form>") holding the
    placeholder-protected source and the machine target, state needs_review;
  * review_queue.create_task() for it, exactly like the pipeline does.

When the reviewer submits, community.review calls pipeline.hooks.segment_reviewed, which
dispatches carrier jobs here (hooks.ADAPTERS). We restore placeholders, write the value back
to the string translation (state reviewed once every form is reviewed), store it in the TM
and close the carrier job when nothing is open. Escalation uses the pipeline's generic
handler (re-queue at senior level). Reviewers see an ordinary task.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.community import queue as review_queue
from arbiter.domain.states import transition
from arbiter.engines import tags
from arbiter.models import (
    FileAsset,
    Job,
    Organization,
    Project,
    Segment,
    StringBranch,
    StringKey,
    StringProject,
    StringTranslation,
    utcnow,
)
from arbiter.pipeline import events
from arbiter.platform.modules import org_has_module
from arbiter.strings import placeholders as ph
from arbiter.strings import service

ADAPTER = "strings"
OPEN = ("needs_review", "in_review")


def _carrier_file(db: Session, proj: StringProject) -> FileAsset:
    fa = db.execute(
        select(FileAsset).where(
            FileAsset.org_id == proj.org_id, FileAsset.format == "strings", FileAsset.sha256 == proj.id
        )
    ).scalar_one_or_none()
    if fa is None:
        fa = FileAsset(
            org_id=proj.org_id,
            filename=f"{proj.name} (strings)",
            format="strings",
            sha256=proj.id,  # marker: the carrier file of this string project, never a real hash
            size=0,
            storage_key="",
            source_lang=proj.base_lang,
        )
        db.add(fa)
        db.flush()
    return fa


def carrier_job(db: Session, proj: StringProject, lang: str) -> Job:
    fa = _carrier_file(db, proj)
    job = db.execute(
        select(Job)
        .where(Job.file_id == fa.id, Job.target_lang == lang, Job.state.in_(("running", "review")))
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if job is not None:
        return job
    prev = db.execute(select(Job.project_id).where(Job.file_id == fa.id).limit(1)).scalar_one_or_none()
    project = db.get(Project, prev) if prev else None
    if project is None:
        project = Project(
            org_id=proj.org_id,
            name=f"Strings review: {proj.name}",
            source_lang=proj.base_lang,
            target_langs=list(proj.target_langs),
            tier=proj.tier,
            content_type="software",
        )
        db.add(project)
        db.flush()
    job = Job(
        project_id=project.id,
        org_id=proj.org_id,
        file_id=fa.id,
        source_lang=proj.base_lang,
        target_lang=lang,
        tier=proj.tier,
        content_type="software",
        state="draft",
        workflow={"adapter": ADAPTER, "string_project_id": proj.id, "steps": []},
    )
    db.add(job)
    db.flush()
    transition(job, "job", "quoted")
    transition(job, "job", "running")
    transition(job, "job", "review")
    job.started_at = utcnow()
    events.record(db, job, "job_started", tier=job.tier, adapter=ADAPTER, string_project_id=proj.id)
    return job


def available(db: Session, proj: StringProject) -> bool:
    org = db.get(Organization, proj.org_id)
    return org is not None and org_has_module(org, "community")


def request_review(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    key: StringKey,
    tr: StringTranslation,
    lang: str,
    *,
    pieces: list[Any] | None = None,
    batch: Any = None,
) -> int:
    """Queue every form of one translation for human review. Returns the number of tasks."""
    if not available(db, proj):
        return 0
    job = carrier_job(db, proj, lang)
    if batch is not None and getattr(batch, "review_job_id", None) is None:
        batch.review_job_id = job.id
    style = service.settings_of(proj)["placeholder_style"]
    base = service.value_of(
        service.effective(db, branch, [key.id], [proj.base_lang]).get((key.id, proj.base_lang))
    )
    value = service.value_of(tr)
    if pieces is None:
        from arbiter.strings.translate import Runner

        pieces = Runner(db, proj, branch, None).pieces(key, base, lang)
    seq = int(
        db.execute(
            select(func.coalesce(func.max(Segment.seq), 0)).where(Segment.job_id == job.id)
        ).scalar_one()
    )
    created = 0
    for p in pieces:
        src: ph.Protected = p.protected
        cur = value.get(p.form or "", "") if isinstance(value, dict) else (value or "")
        from arbiter.strings.translate import _protect_like

        target_tagged = _protect_like(cur, src, style) or ph.protect(cur, style).tagged
        unit = f"strtr:{tr.id}:{p.form or ''}"
        exists = db.execute(
            select(Segment.id).where(
                Segment.job_id == job.id, Segment.unit_id == unit, Segment.state.in_(OPEN)
            )
        ).first()
        if exists:
            continue
        seq += 1
        plain = tags.plain(src.tagged)
        seg = Segment(
            job_id=job.id,
            seq=seq,
            unit_id=unit,
            seg_index=0,
            context=f"key:{key.name}" + (f" [{p.form}]" if p.form else ""),
            max_length=key.max_length if key.kind == "string" else None,
            source_tagged=src.tagged,
            source_plain=plain,
            source_codes=[
                {"id": str(i + 1), "kind": "standalone", "original": c, "display": c}
                for i, c in enumerate(src.codes)
            ],
            target_tagged=target_tagged,
            engine_target_tagged=target_tagged,
            word_count=len(plain.split()),
            state="pending",
            origin=tr.origin or "mt",
            engine=tr.engine,
            qe_score=tr.qe_score,
            decision="review",
            reasons=["strings_review"],
            signals={
                "terms": [
                    {"source_term": h.source_term, "target_term": h.target_term, "kind": h.kind}
                    for h in getattr(p, "hits", [])
                ],
                "errors": [i for i in (tr.qa or []) if i.get("form") in (None, p.form)],
                "strings": {
                    "project_id": proj.id,
                    "branch_id": branch.id,
                    "key_id": key.id,
                    "translation_id": tr.id,
                    "lang": lang,
                    "form": p.form,
                },
            },
        )
        db.add(seg)
        db.flush()
        transition(seg, "segment", "translated")
        transition(seg, "segment", "needs_review")
        events.record(
            db,
            job,
            "target_set",
            segment=seg,
            actor_type="engine",
            actor_id=tr.engine or "",
            origin="strings",
        )
        task = review_queue.create_task(db, seg, job)
        job.segment_count += 1
        job.review_count += 1
        tr.review_task_id = tr.review_task_id or task.id
        created += 1
    db.flush()
    return created


def on_segment_reviewed(
    session: Session,
    segment_id: str,
    *,
    target_tagged: str,
    reviewer_id: str,
    decision: str,
    errors: list[dict[str, Any]],
) -> None:
    """hooks.segment_reviewed for carrier jobs: write the reviewed value back to the string."""
    seg = session.get(Segment, segment_id)
    if seg is None or seg.state not in OPEN:
        return
    job = session.get(Job, seg.job_id, with_for_update=True)
    info = (seg.signals or {}).get("strings") or {}
    tr = session.get(StringTranslation, info.get("translation_id", ""))
    proj = session.get(StringProject, info.get("project_id", ""))
    key = session.get(StringKey, info.get("key_id", ""))
    if job is None or tr is None or proj is None or key is None:
        return
    codes = [str(c.get("original", "")) for c in seg.source_codes or []]
    try:
        restored = ph.restore(target_tagged, codes)
    except ph.TaggedParseError:
        restored = tags.plain(target_tagged)
    if decision == "edit" and target_tagged != seg.target_tagged:
        seg.target_tagged = target_tagged
        seg.origin = "human"
    seg.reviewer_id = reviewer_id
    seg.updated_at = utcnow()
    transition(seg, "segment", "reviewed")
    events.record(
        session, job, "reviewed", segment=seg, actor_type="human", actor_id=reviewer_id, decision=decision
    )

    branch = session.get(StringBranch, tr.branch_id)
    if branch is None or branch.merged_at is not None:
        branch = service.main_branch(session, proj)
    form = info.get("form")
    cur = service.value_of(tr)
    value: Any = restored if form is None else {**(cur if isinstance(cur, dict) else {}), form: restored}
    still_open = session.execute(
        select(func.count())
        .select_from(Segment)
        .where(
            Segment.job_id == job.id,
            Segment.unit_id.like(f"strtr:{tr.id}:%"),
            Segment.state.in_(OPEN),
        )
    ).scalar_one()
    from arbiter.strings.qa import check_value
    from arbiter.strings.translate import store_tm

    base = service.value_of(
        service.effective(session, branch, [key.id], [proj.base_lang]).get((key.id, proj.base_lang))
    )
    s = service.settings_of(proj)
    issues = check_value(key, base, value, tr.lang, style=s["placeholder_style"], rules=s["plural_rules"])
    blocked = any(i["blocking"] for i in issues)
    done = still_open == 0
    service.write_translation(
        session,
        proj,
        branch,
        key,
        tr.lang,
        value,
        state="reviewed" if done and not blocked else "machine",
        origin="review",
        event="reviewed",
        actor_type="human",
        actor_id=reviewer_id,
        qa=issues,
        blocked=blocked,
        needs_review=not done or blocked,
        decision=decision,
        errors=errors,
        task_segment=seg.id,
    )
    if done and not blocked:
        store_tm(session, proj, key, tr.lang, base, value, origin="review")
    _maybe_close(session, job)


def _maybe_close(session: Session, job: Job) -> None:
    open_count = session.execute(
        select(func.count()).select_from(Segment).where(Segment.job_id == job.id, Segment.state.in_(OPEN))
    ).scalar_one()
    if open_count or job.state != "review":
        return
    for st in ("ready", "merging", "delivered"):
        transition(job, "job", st)
    job.delivered_at = utcnow()
    events.record(session, job, "delivered", adapter=ADAPTER)

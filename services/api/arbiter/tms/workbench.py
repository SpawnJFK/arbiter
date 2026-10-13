"""Segment editor operations: live QA of a draft, TM and term assistance, MT on demand,
split and merge, find and replace, PM locks, the editor's filtered segment list.

Rules
- A draft check never saves anything (POST .../check).
- Split and merge keep every inline code on the side of the cut it belongs to; a cut
  inside a code, between the halves of an escape or inside an open formatting pair is
  refused. Merge joins only adjacent segments of the same unit. Both renumber seq and
  seg_index and record provenance on every segment involved; units.slots_of keeps the
  merge back into the file exact (see pipeline/units.py).
- Find and replace touches text runs only (never codes), previews first, writes one
  provenance event per changed segment, and skips locked or approved segments unless a
  PM forces it.
- A locked segment is read-only for everyone except a PM (who can unlock it).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from arbiter.contracts import MtRequest, SegmentContext
from arbiter.engines.registry import get_mt
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.fileproc.base import from_tagged, validate_tags
from arbiter.linguistic import tm
from arbiter.models import Job, Organization, Segment, SegmentComment, new_id, utcnow
from arbiter.pipeline import events, orchestrator
from arbiter.pipeline.units import slots_of
from arbiter.quality.checks import run_hard_checks
from arbiter.tms import tagged

EDITABLE_STATES = ("needs_review", "auto_approved", "reviewed")
APPROVED_STATES = ("auto_approved", "reviewed")
OPEN_JOB_STATES = ("running", "review")
NO_SPACE_LANGS = ("zh", "ja", "th", "lo", "km", "my")
TM_BANDS = ("none", "lt75", "75-84", "85-94", "95-99", "100", "101")


class SegmentLocked(Conflict):
    code = "segment_locked"


class TagError(Invalid):
    code = "tag_error"


def _primary(lang: str) -> str:
    return (lang or "").lower().replace("_", "-").split("-")[0]


def _sep(lang: str) -> str:
    return "" if _primary(lang) in NO_SPACE_LANGS else " "


def _words(text: str) -> int:
    return len(text.split())


def ensure_open(job: Job) -> None:
    if job.state not in OPEN_JOB_STATES:
        raise Conflict(f"segments of a {job.state} job cannot be changed in the editor")


def ensure_unlocked(seg: Segment, role: str) -> None:
    if seg.locked_by and role != "pm":
        raise SegmentLocked("this segment is locked by the project manager")


# --------------------------------------------------------------------------- live QA


def _ctx(session: Session, job: Job, seg: Segment, target: str) -> tuple[SegmentContext, list[Any]]:
    terms = orchestrator._terms_for(session, job)
    hits = orchestrator._hits(seg, terms, job.source_lang)
    ctx = SegmentContext(
        segment_id=seg.id,
        source_tagged=seg.source_tagged,
        target_tagged=target,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        content_type=job.content_type,
        terms=hits,
        max_length=seg.max_length,
    )
    return ctx, hits


def check_draft(session: Session, job: Job, seg: Segment, target: str) -> dict[str, Any]:
    """Hard QA checks (tags, numbers, placeholders, length, glossary) on an unsaved draft."""
    ctx, hits = _ctx(session, job, seg, target)
    violations = orchestrator._violations(target, hits, job.target_lang)
    issues = run_hard_checks(ctx, violations)
    return {
        "issues": [asdict(i) for i in issues],
        "blocking": any(i.blocking for i in issues),
        "terms": [_hit(h) for h in hits],
        "term_violations": [asdict(v) for v in violations],
    }


def _hit(h: Any) -> dict[str, Any]:
    return {
        "term_id": h.term_id,
        "kind": h.kind,
        "source_term": h.source_term,
        "target_term": h.target_term,
        "start": h.start,
        "end": h.end,
        "note": h.note,
    }


# --------------------------------------------------------------------------- assistance

_DIFF_TOKEN = re.compile(r"\w+|\s+|[^\w\s]", re.U)


def word_diff(old: str, new: str) -> list[dict[str, str]]:
    """Token diff from a TM match source (old) to the current source (new):
    equal | delete (only in the TM source) | insert (only in the current source)."""
    a, b = _DIFF_TOKEN.findall(old), _DIFF_TOKEN.findall(new)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            out.append({"op": "delete", "text": "".join(a[i1:i2])})
        if j2 > j1:
            out.append({"op": "insert", "text": "".join(b[j1:j2])})
    return out


def assist(session: Session, job: Job, seg: Segment) -> dict[str, Any]:
    """Right panel data: TM matches with a diff against the current source, glossary hits."""
    matches = tm.lookup(
        session,
        job.org_id,
        job.source_lang,
        job.target_lang,
        seg.source_tagged,
        (seg.signals or {}).get("context_hash"),
        min_fuzzy=50.0,
        limit=5,
    )
    terms = orchestrator._terms_for(session, job)
    hits = orchestrator._hits(seg, terms, job.source_lang)
    return {
        "tm_matches": [
            {
                "entry_id": m.entry_id,
                "kind": m.kind,
                "score": m.score,
                "source_tagged": m.source_tagged,
                "target_tagged": m.target_tagged,
                "diff": word_diff(tm.tagged_plain(m.source_tagged), seg.source_plain),
            }
            for m in matches
        ],
        "terms": [_hit(h) for h in hits],
    }


def mt_suggest(session: Session, job: Job, seg: Segment, engine: str | None = None) -> dict[str, Any]:
    """One MT suggestion for the segment, engine chosen like the pipeline does for this org
    (scoreboard, default, workflow preference) unless the caller names an available one.
    Nothing is saved; the cost is added to the job."""
    names = orchestrator._engine_names(session, job)
    if engine:
        if engine not in names:
            raise Invalid(f"engine {engine!r} is not available; choose one of {', '.join(names) or 'none'}")
        names = [engine]
    else:
        from arbiter.agency import workflows as wfl

        mt_step = wfl.step(job.workflow, "mt")
        preferred = (mt_step.get("params") or {}).get("engine") if mt_step else None
        if preferred in names:
            names = [preferred] + [n for n in names if n != preferred]
    if not names:
        raise Conflict("no MT engine is available for this organization")
    terms = orchestrator._terms_for(session, job)
    hits = orchestrator._hits(seg, terms, job.source_lang)
    style, formality = orchestrator._style(session, job)
    req = MtRequest(
        source_tagged=seg.source_tagged,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        terms=hits,
        style_rules=style,
        formality=formality,
        max_length=seg.max_length,
    )
    last = "no engine answered"
    for name in names:
        try:
            res = get_mt(name).translate([req])[0]
        except Exception as e:  # provider down: try the next engine, like the pipeline
            last = str(e)
            continue
        if res.error or not res.target_tagged:
            last = res.error or "empty result"
            continue
        job.cost_engines = (job.cost_engines or 0) + (res.usage.cost or 0)
        return {"target_tagged": res.target_tagged, "engine": res.engine, "model_version": res.model_version}
    raise Conflict(f"machine translation failed: {last}")


# --------------------------------------------------------------------------- locks


def set_lock(session: Session, job: Job, segs: list[Segment], locked: bool, actor: str) -> int:
    n = 0
    now = utcnow()
    for seg in segs:
        if bool(seg.locked_by) == locked:
            continue
        seg.locked_by = actor if locked else None
        seg.locked_at = now if locked else None
        events.record(
            session, job, "locked" if locked else "unlocked", segment=seg, actor_type="human", actor_id=actor
        )
        n += 1
    session.flush()
    return n


# --------------------------------------------------------------------------- split / merge


def _codes_in(seg: Segment, text: str) -> list[dict[str, Any]]:
    keys = set(tagged.code_keys(text))
    return [c for c in (seg.source_codes or []) if (c["id"], c["kind"]) in keys]


def _requeue(session: Session, job: Job, segs: list[Segment]) -> None:
    """Segments still waiting for a human get fresh review tasks for their new content."""
    from arbiter.community import queue as review_queue

    org = session.get(Organization, job.org_id)
    assert org is not None
    for s in segs:
        orchestrator._cancel_tasks(session, s)
    session.flush()
    for s in segs:
        if s.state == "needs_review":
            review_queue.create_task(session, s, job, min_level=orchestrator._level_for(org, "review", job))


def _check_part_tags(source_part: str, codes: list[dict[str, Any]], target_part: str) -> None:
    from arbiter.fileproc.base import InlineCode

    content = from_tagged(source_part, [InlineCode(**c) for c in codes])
    errors = [i for i in validate_tags(content, target_part) if i.severity == "error"]
    if errors:
        raise TagError(
            "each half of the translation must keep the inline codes of its half of the source",
            {"issues": [{"kind": i.kind, "code_id": i.code_id, "detail": i.detail} for i in errors]},
        )


def split(
    session: Session, job: Job, seg: Segment, source_offset: int, target_offset: int | None, actor: str
) -> tuple[Segment, Segment]:
    """Split one segment in two at character offsets of the tagged source (and target)."""
    ensure_open(job)
    if seg.state not in EDITABLE_STATES:
        raise Conflict(f"a segment in state {seg.state} cannot be split")
    src = seg.source_tagged
    if not tagged.is_boundary(src, source_offset):
        raise Invalid("the split point must be inside the source text, outside any inline code")
    s1, s2 = src[:source_offset], src[source_offset:]
    if not tagged.balanced(s1) or not tagged.balanced(s2):
        raise Invalid("the split point cannot fall inside a formatting pair")
    if not tagged.plain(s1).strip() or not tagged.plain(s2).strip():
        raise Invalid("both parts of the split must contain text")
    c1, c2 = _codes_in(seg, s1), _codes_in(seg, s2)
    t1: str | None = None
    t2: str | None = None
    if seg.target_tagged:
        tgt = seg.target_tagged
        if target_offset is None:
            raise Invalid("target_offset is required when the segment has a translation")
        if not (0 <= target_offset <= len(tgt)) or (
            0 < target_offset < len(tgt) and not tagged.is_boundary(tgt, target_offset)
        ):
            raise Invalid("the target split point must be outside any inline code")
        t1, t2 = tgt[:target_offset], tgt[target_offset:]
        _check_part_tags(s1, c1, t1)
        _check_part_tags(s2, c2, t2)

    # make room: everything after this segment moves one place down
    session.execute(
        update(Segment).where(Segment.job_id == job.id, Segment.seq > seg.seq).values(seq=Segment.seq + 1)
    )
    session.execute(
        update(Segment)
        .where(Segment.job_id == job.id, Segment.unit_id == seg.unit_id, Segment.seg_index > seg.seg_index)
        .values(seg_index=Segment.seg_index + 1)
    )
    new = Segment(
        id=new_id("seg"),
        job_id=job.id,
        seq=seg.seq + 1,
        unit_id=seg.unit_id,
        seg_index=seg.seg_index + 1,
        context=seg.context,
        max_length=None,
        source_tagged=s2,
        source_plain=tagged.plain(s2),
        source_codes=c2,
        target_tagged=t2 or None,
        word_count=_words(tagged.plain(s2)),
        state=seg.state,  # a new row starts where its parent was (not a transition)
        origin=seg.origin,
        engine=seg.engine,
        decision=seg.decision,
        signals={"slots": 0, "split_from": seg.id},
        reasons=[],
        engine_target_tagged=None,
        updated_at=utcnow(),
    )
    seg.source_tagged = s1
    seg.source_plain = tagged.plain(s1)
    seg.source_codes = c1
    seg.target_tagged = t1 if t1 is not None else seg.target_tagged
    seg.word_count = _words(seg.source_plain)
    seg.engine_target_tagged = None
    seg.updated_at = utcnow()
    session.add(new)
    session.flush()
    job.segment_count = (job.segment_count or 0) + 1
    events.record(
        session,
        job,
        "split",
        segment=seg,
        actor_type="human",
        actor_id=actor,
        new_segment=new.id,
        source=s1,
        target=t1,
        source_offset=source_offset,
        target_offset=target_offset,
    )
    events.record(
        session,
        job,
        "split_created",
        segment=new,
        actor_type="human",
        actor_id=actor,
        from_segment=seg.id,
        source=s2,
        target=t2,
    )
    _requeue(session, job, [seg, new])
    session.flush()
    return seg, new


def merge_next(session: Session, job: Job, seg: Segment, actor: str) -> Segment:
    """Merge a segment with the next one of the same unit. Returns the surviving segment."""
    ensure_open(job)
    nxt = session.execute(
        select(Segment)
        .where(
            Segment.job_id == job.id,
            Segment.unit_id == seg.unit_id,
            Segment.seg_index == seg.seg_index + 1,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if nxt is None:
        raise Conflict("only adjacent segments of the same unit (paragraph, cell, entry) can be merged")
    for s in (seg, nxt):
        if s.state not in EDITABLE_STATES:
            raise Conflict(f"a segment in state {s.state} cannot be merged")
        if s.locked_by:
            raise SegmentLocked("unlock both segments before merging them")
    ids_a = {c["id"] for c in (seg.source_codes or [])}
    if any(c["id"] in ids_a for c in (nxt.source_codes or [])):
        raise Conflict("these segments reuse inline code ids and cannot be merged")
    src_sep = "" if slots_of(nxt) == 0 else _sep(job.source_lang)
    tgt_sep = "" if slots_of(nxt) == 0 else _sep(job.target_lang)
    source = seg.source_tagged + src_sep + nxt.source_tagged
    targets = [t for t in (seg.target_tagged, nxt.target_tagged) if t]
    target = tgt_sep.join(targets) if targets else None
    # The survivor keeps the "less done" state: an approved row cannot go back to review.
    keep, gone = (nxt, seg) if seg.state in APPROVED_STATES and nxt.state == "needs_review" else (seg, nxt)
    slots = slots_of(seg) + slots_of(nxt)
    codes = list(seg.source_codes or []) + list(nxt.source_codes or [])
    signals = {**(keep.signals or {}), "slots": slots}
    signals.pop("split_from", None)
    events.record(
        session,
        job,
        "merged_away",
        segment=gone,
        actor_type="human",
        actor_id=actor,
        into=keep.id,
        source=gone.source_tagged,
        target=gone.target_tagged,
    )
    session.execute(
        update(SegmentComment).where(SegmentComment.segment_id == gone.id).values(segment_id=keep.id)
    )
    first_seq, first_index = seg.seq, seg.seg_index
    orchestrator._cancel_tasks(session, gone)
    session.flush()  # tasks first: review_tasks has no ORM relationship to order the deletes
    session.delete(gone)
    session.flush()
    keep.seq, keep.seg_index = first_seq, first_index
    keep.source_tagged = source
    keep.source_plain = tagged.plain(source)
    keep.source_codes = codes
    keep.target_tagged = target
    keep.word_count = _words(keep.source_plain)
    keep.signals = signals
    keep.engine_target_tagged = None
    keep.updated_at = utcnow()
    session.flush()
    session.execute(
        update(Segment)
        .where(Segment.job_id == job.id, Segment.seq > first_seq + 1)
        .values(seq=Segment.seq - 1)
    )
    session.execute(
        update(Segment)
        .where(Segment.job_id == job.id, Segment.unit_id == keep.unit_id, Segment.seg_index > first_index + 1)
        .values(seg_index=Segment.seg_index - 1)
    )
    job.segment_count = max(0, (job.segment_count or 0) - 1)
    events.record(
        session,
        job,
        "merged",
        segment=keep,
        actor_type="human",
        actor_id=actor,
        removed=gone.id,
        source=source,
        target=target,
    )
    _requeue(session, job, [keep])
    session.flush()
    session.refresh(keep)
    return keep


# --------------------------------------------------------------------------- find & replace


def _pattern(find: str, regex: bool, case_sensitive: bool, whole_word: bool) -> re.Pattern[str]:
    body = find if regex else re.escape(find)
    if whole_word:
        body = rf"\b(?:{body})\b"
    try:
        return re.compile(body, 0 if case_sensitive else re.IGNORECASE)
    except re.error as e:
        raise Invalid(f"invalid regular expression: {e}") from None


def find_replace(
    session: Session,
    job: Job,
    *,
    find: str,
    replace: str | None,
    regex: bool,
    case_sensitive: bool,
    whole_word: bool,
    scope: str,
    states: list[str] | None,
    segment_ids: list[str] | None,
    apply: bool,
    force: bool,
    role: str,
    actor: str,
    limit: int = 500,
) -> dict[str, Any]:
    """Preview (apply=False) or apply a find/replace over the job. Replacement is target only."""
    if apply:
        ensure_open(job)
        if replace is None:
            raise Invalid("replace is required to apply")
        if scope == "source":
            raise Invalid("only the target can be replaced; the source is read-only")
    if force and role != "pm":
        raise Conflict("only a project manager can force changes to locked or approved segments")
    pat = _pattern(find, regex, case_sensitive, whole_word)
    q = select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)
    if states:
        q = q.where(Segment.state.in_(states))
    if segment_ids:
        q = q.where(Segment.id.in_(segment_ids))
    if apply:
        q = q.with_for_update()
    items: list[dict[str, Any]] = []
    changed = skipped = total_matches = 0
    for seg in session.execute(q).scalars():
        src_hits = len(pat.findall(seg.source_plain)) if scope in ("source", "both") else 0
        tgt_text = seg.target_tagged or ""
        tgt_hits = len(pat.findall(tagged.plain(tgt_text))) if scope in ("target", "both") else 0
        if not src_hits and not tgt_hits:
            continue
        total_matches += src_hits + tgt_hits
        after: str | None = None
        reason: str | None = None
        if replace is not None and tgt_hits:
            after, _n = tagged.replace_in_text(tgt_text, pat, replace, literal=not regex)
            if seg.state not in EDITABLE_STATES:
                reason = "state"
            elif seg.locked_by and not force:
                reason = "locked"
            elif seg.state in APPROVED_STATES and not force:
                reason = "approved"
            else:
                try:
                    content = from_tagged(seg.source_tagged, orchestrator._codes(seg))
                    if [i for i in validate_tags(content, after) if i.severity == "error"]:
                        reason = "tag_error"
                except ValueError:
                    reason = "tag_error"
            if after == tgt_text:
                after, reason = None, reason or "unchanged"
        item = {
            "segment_id": seg.id,
            "seq": seg.seq,
            "state": seg.state,
            "locked": bool(seg.locked_by),
            "source_matches": src_hits,
            "target_matches": tgt_hits,
            "source_tagged": seg.source_tagged,
            "before": seg.target_tagged,
            "after": after,
            "skip_reason": reason,
        }
        if apply and after is not None and reason is None:
            orchestrator._set_target(
                session, job, seg, after, origin="human", actor=actor, by="find_replace", find=find
            )
            if seg.state in APPROVED_STATES:
                orchestrator._learn(session, job, seg)
            changed += 1
        elif apply and replace is not None and tgt_hits:
            skipped += 1
        if len(items) < limit:
            items.append(item)
    session.flush()
    return {
        "items": items,
        "total_matches": total_matches,
        "segments": len(items),
        "changed": changed,
        "skipped": skipped,
        "applied": apply,
    }


# --------------------------------------------------------------------------- editor list


def editor_query(
    job: Job,
    *,
    state: list[str] | None = None,
    decision: str | None = None,
    locked: bool | None = None,
    has_comment: bool | None = None,
    open_query: bool | None = None,
    qa: bool | None = None,
    tm_band: str | None = None,
    q: str | None = None,
) -> Any:
    stmt = select(Segment).where(Segment.job_id == job.id)
    if state:
        stmt = stmt.where(Segment.state.in_(state))
    if decision:
        stmt = stmt.where(Segment.decision == decision)
    if locked is not None:
        stmt = stmt.where(Segment.locked_by.is_not(None) if locked else Segment.locked_by.is_(None))
    if has_comment is not None:
        has = exists().where(SegmentComment.segment_id == Segment.id)
        stmt = stmt.where(has if has_comment else ~has)
    if open_query is not None:
        has_q = exists().where(
            SegmentComment.segment_id == Segment.id,
            SegmentComment.kind == "query",
            SegmentComment.resolved.is_(False),
            SegmentComment.thread_id == SegmentComment.id,
        )
        stmt = stmt.where(has_q if open_query else ~has_q)
    if qa is not None:
        n_issues = func.coalesce(func.json_array_length(Segment.signals["hard_issues"]), 0)
        stmt = stmt.where(n_issues > 0 if qa else n_issues == 0)
    if tm_band:
        if tm_band not in TM_BANDS:
            raise Invalid(f"tm_band must be one of {', '.join(TM_BANDS)}")
        col = Segment.tm_match
        cond = {
            "none": col.is_(None),
            "lt75": col < 75,
            "75-84": (col >= 75) & (col < 85),
            "85-94": (col >= 85) & (col < 95),
            "95-99": (col >= 95) & (col < 100),
            "100": (col >= 100) & (col < 101),
            "101": col >= 101,
        }[tm_band]
        stmt = stmt.where(cond)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Segment.source_plain.ilike(like) | Segment.target_tagged.ilike(like))
    return stmt.order_by(Segment.seq)


def comment_counts(session: Session, seg_ids: list[str]) -> dict[str, dict[str, int]]:
    if not seg_ids:
        return {}
    rows = session.execute(
        select(SegmentComment.segment_id, SegmentComment.kind, SegmentComment.resolved, func.count())
        .where(SegmentComment.segment_id.in_(seg_ids), SegmentComment.thread_id == SegmentComment.id)
        .group_by(SegmentComment.segment_id, SegmentComment.kind, SegmentComment.resolved)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for sid, kind, resolved, n in rows:
        d = out.setdefault(sid, {"threads": 0, "open_queries": 0})
        d["threads"] += int(n)
        if kind == "query" and not resolved:
            d["open_queries"] += int(n)
    return out


def get_segment(session: Session, job: Job, seg_id: str, *, lock: bool = False) -> Segment:
    q = select(Segment).where(Segment.id == seg_id, Segment.job_id == job.id)
    if lock:
        q = q.with_for_update()
    seg = session.execute(q).scalar_one_or_none()
    if seg is None:
        raise NotFound("segment not found")
    return seg


__all__ = [
    "APPROVED_STATES",
    "EDITABLE_STATES",
    "SegmentLocked",
    "TagError",
    "assist",
    "check_draft",
    "comment_counts",
    "editor_query",
    "ensure_open",
    "ensure_unlocked",
    "find_replace",
    "get_segment",
    "merge_next",
    "mt_suggest",
    "set_lock",
    "split",
    "word_diff",
]

"""Audit pipeline on the work queue (each step idempotent, progress committed per batch).

    audit.parse   read the file(s) into audit_segments           queued -> running
    audit.check   hard QA + glossary + optional AI MQM judge, BATCH segments per item
    audit.finish  consistency checks, scorecard, verdict, AI usage   running -> done

AI cost control: settings.ai_mode none | sample | full; sample picks ai_sample_pct percent
of the segments deterministically (hash of audit id and position), so a rerun samples the
same segments. Segments with a blocking hard issue never reach the model (judge.py).
Hard QA issues count in the MQM score too, mapped by QA_MQM below.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.auditor import bilingual
from arbiter.config import get_settings
from arbiter.contracts import SEVERITY_WEIGHT, EngineError, SegmentContext, TermHit
from arbiter.domain.states import transition
from arbiter.fileproc.base import FormatError
from arbiter.linguistic import glossary as gl
from arbiter.linguistic.tm import _lang_clause, tagged_plain
from arbiter.models import Audit, AuditSegment, Organization, Term, utcnow
from arbiter.pipeline.queue import enqueue
from arbiter.quality import scorecard
from arbiter.quality.checks import run_hard_checks
from arbiter.quality.judge import judge
from arbiter.quality.mqm import evaluation_word_count

log = logging.getLogger(__name__)
BATCH = 100
AI_MODES = ("none", "sample", "full")
SEV_ORDER = ("none", "neutral", "minor", "major", "critical")

# hard QA code -> MQM dimension; severity: blocking error -> major, warning -> minor, info -> neutral
QA_MQM: dict[str, str] = {
    "empty_target": "accuracy",
    "untranslated": "accuracy",
    "number_mismatch": "accuracy",
    "url_email_mismatch": "accuracy",
    "placeholder_mismatch": "design_and_markup",
    "length_exceeded": "design_and_markup",
    "whitespace_mismatch": "linguistic_conventions",
    "double_space": "linguistic_conventions",
    "repeated_word": "linguistic_conventions",
    "punctuation_end": "linguistic_conventions",
    "term_missing": "terminology",
    "term_forbidden": "terminology",
    "dnt_changed": "terminology",
    "term_preferred_missing": "terminology",
    "inconsistent_translation": "terminology",
    "inconsistent_source": "style",
}


def _qa_dimension(code: str) -> str:
    return "design_and_markup" if code.startswith("tag_") else QA_MQM.get(code, "accuracy")


def _qa_severity(severity: str, blocking: bool) -> str:
    if blocking or severity == "error":
        return "major"
    return "minor" if severity == "warning" else "neutral"


def _audit(session: Session, audit_id: str) -> Audit | None:
    return session.execute(select(Audit).where(Audit.id == audit_id).with_for_update()).scalar_one_or_none()


def fail(session: Session, audit_id: str, reason: str) -> None:
    audit = _audit(session, audit_id)
    if audit is None or audit.state in ("done", "failed"):
        return
    audit.error = reason[:2000]
    audit.finished_at = utcnow()
    transition(audit, "audit", "failed")


def _attempt(audit: Audit) -> int:
    return int((audit.summary or {}).get("attempt", 0))


def _picked(audit: Audit, seq: int) -> bool:
    mode = (audit.settings or {}).get("ai_mode", "none")
    if mode == "full":
        return True
    if mode != "sample":
        return False
    pct = float((audit.settings or {}).get("ai_sample_pct", 10))
    h = int(hashlib.sha256(f"{audit.id}:{seq}".encode()).hexdigest()[:8], 16) % 10_000
    return h < pct * 100


# --------------------------------------------------------------------------- steps


def parse(session: Session, payload: dict[str, Any]) -> None:
    audit = _audit(session, payload["audit_id"])
    if audit is None or audit.state != "queued":
        return
    transition(audit, "audit", "running")
    audit.started_at = utcnow()
    try:
        data = storage.get(audit.storage_key)
        tdata = storage.get(audit.target_storage_key) if audit.target_storage_key else None
        segs, notes = bilingual.read(
            audit.input_format,
            data,
            audit.source_lang,
            audit.target_lang,
            filename=audit.filename,
            target_name=audit.target_filename,
            target_data=tdata,
        )
    except (FormatError, FileNotFoundError) as e:
        audit.error = str(e) if isinstance(e, FormatError) else "the uploaded file is no longer stored"
        audit.finished_at = utcnow()
        transition(audit, "audit", "failed")
        return
    session.execute(delete(AuditSegment).where(AuditSegment.audit_id == audit.id))
    words = 0
    for i, s in enumerate(segs):
        wc = evaluation_word_count(tagged_plain(s.source_tagged), audit.source_lang)
        words += wc
        session.add(
            AuditSegment(
                audit_id=audit.id,
                seq=i,
                unit_id=s.ref[:200],
                source_tagged=s.source_tagged,
                target_tagged=s.target_tagged,
                word_count=wc,
                issues=[],
                mqm_errors=[],
            )
        )
    audit.segments_total = len(segs)
    audit.segments_done = 0
    audit.word_count = words
    attempt = _attempt(audit)
    audit.summary = {"attempt": attempt, "notes": notes}
    audit.progress = 0.02
    enqueue(
        session,
        "audit.check",
        {"audit_id": audit.id, "offset": 0},
        idempotency_key=f"{audit.id}:{attempt}:check:0",
    )


def _terms(session: Session, audit: Audit) -> list[Term]:
    if not audit.glossary_id:
        return []
    return list(
        session.execute(
            select(Term).where(
                Term.glossary_id == audit.glossary_id,
                Term.valid_to.is_(None),
                _lang_clause(Term.source_lang, audit.source_lang),
                _lang_clause(Term.target_lang, audit.target_lang),
            )
        ).scalars()
    )


def _issue(code: str, severity: str, message: str, blocking: bool, kind: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "blocking": blocking,
        "kind": kind,
        "dimension": _qa_dimension(code),
        "mqm_severity": _qa_severity(severity, blocking),
    }


def _finalize_segment(seg: AuditSegment) -> None:
    rows = [{"dimension": i["dimension"], "severity": i["mqm_severity"]} for i in seg.issues or []]
    rows += [{"dimension": e["dimension"], "severity": e["severity"]} for e in seg.mqm_errors or []]
    sevs = [r["severity"] for r in rows]
    seg.max_severity = max(sevs, key=SEV_ORDER.index) if sevs else "none"
    seg.dimensions = sorted({r["dimension"] for r in rows})
    apt = sum(SEVERITY_WEIGHT.get(s, 0) for s in sevs)
    seg.score = round(min(100.0, max(0.0, 100.0 - apt * 100.0 / max(seg.word_count, 1))), 2)


def check(session: Session, payload: dict[str, Any]) -> None:
    audit = _audit(session, payload["audit_id"])
    if audit is None or audit.state != "running":
        return
    offset = int(payload.get("offset", 0))
    segs = list(
        session.execute(
            select(AuditSegment)
            .where(AuditSegment.audit_id == audit.id, AuditSegment.seq >= offset)
            .order_by(AuditSegment.seq)
            .limit(BATCH)
        ).scalars()
    )
    terms = _terms(session, audit)
    llm = None
    ai_calls = ai_failed = 0
    for seg in segs:
        if seg.checked:
            continue  # a retried batch: already done
        src_plain = tagged_plain(seg.source_tagged)
        hits: list[TermHit] = gl.find_source_terms(src_plain, terms, audit.source_lang) if terms else []
        violations = gl.check_target(tagged_plain(seg.target_tagged), hits, audit.target_lang) if hits else []
        ctx = SegmentContext(
            segment_id=seg.id,
            source_tagged=seg.source_tagged,
            target_tagged=seg.target_tagged,
            source_lang=audit.source_lang,
            target_lang=audit.target_lang,
            content_type=(audit.settings or {}).get("content_type", "general"),
            terms=hits,
        )
        issues = run_hard_checks(ctx, violations)
        term_codes = {v.code for v in violations}
        seg.issues = [
            _issue(i.code, i.severity, i.message, i.blocking, "term" if i.code in term_codes else "qa")
            for i in issues
        ]
        seg.mqm_errors = []
        if _picked(audit, seg.seq) and seg.target_tagged.strip():
            if llm is None:
                from arbiter.engines.registry import get_llm

                llm = get_llm(get_settings().default_judge_engine)
            try:
                res = judge(ctx, llm, violations)
            except EngineError as e:
                ai_failed += 1
                log.warning("audit %s: judge failed on segment %s: %s", audit.id, seg.seq, e)
            else:
                if res.model_version != "hard-checks":
                    ai_calls += 1
                    seg.ai_checked = True
                    seg.mqm_errors = [{**asdict(e), "source": "ai"} for e in res.errors]
        _finalize_segment(seg)
        seg.checked = True
    summ = dict(audit.summary or {})
    ai = dict(summ.get("ai") or {"checked": 0, "failed": 0})
    ai["checked"] = int(ai.get("checked", 0)) + ai_calls
    ai["failed"] = int(ai.get("failed", 0)) + ai_failed
    summ["ai"] = ai
    audit.summary = summ
    audit.segments_done = min(audit.segments_total, offset + len(segs))
    audit.progress = round(0.02 + 0.93 * audit.segments_done / max(audit.segments_total, 1), 4)
    nxt = offset + BATCH
    attempt = _attempt(audit)
    if len(segs) == BATCH and nxt < audit.segments_total:
        enqueue(
            session,
            "audit.check",
            {"audit_id": audit.id, "offset": nxt},
            idempotency_key=f"{audit.id}:{attempt}:check:{nxt}",
        )
    else:
        enqueue(
            session, "audit.finish", {"audit_id": audit.id}, idempotency_key=f"{audit.id}:{attempt}:finish"
        )


def _norm(text: str) -> str:
    return " ".join(tagged_plain(text).split()).casefold()


def _consistency(segs: list[AuditSegment]) -> dict[str, int]:
    """Same source, different targets (inconsistent_translation, warning) and same target for
    different sources (inconsistent_source, info)."""
    by_src: dict[str, list[AuditSegment]] = defaultdict(list)
    by_tgt: dict[str, list[AuditSegment]] = defaultdict(list)
    for s in segs:
        if s.target_tagged.strip():
            by_src[_norm(s.source_tagged)].append(s)
            by_tgt[_norm(s.target_tagged)].append(s)
    n_src = n_tgt = 0
    for group in by_src.values():
        targets = {_norm(s.target_tagged) for s in group}
        if len(targets) > 1:
            n_src += 1
            for s in group:
                others = sorted(
                    {f"#{o.seq + 1}" for o in group if _norm(o.target_tagged) != _norm(s.target_tagged)}
                )
                s.issues = [
                    *(s.issues or []),
                    _issue(
                        "inconsistent_translation",
                        "warning",
                        f"the same source is translated differently in segment(s) {', '.join(others[:10])}",
                        False,
                        "consistency",
                    ),
                ]
    for group in by_tgt.values():
        sources = {_norm(s.source_tagged) for s in group}
        if len(sources) > 1:
            n_tgt += 1
            for s in group:
                others = sorted(
                    {f"#{o.seq + 1}" for o in group if _norm(o.source_tagged) != _norm(s.source_tagged)}
                )
                s.issues = [
                    *(s.issues or []),
                    _issue(
                        "inconsistent_source",
                        "info",
                        f"the same translation is used for different sources in segment(s) {', '.join(others[:10])}",
                        False,
                        "consistency",
                    ),
                ]
    for group in (*by_src.values(), *by_tgt.values()):
        for s in group:
            _finalize_segment(s)
    return {"inconsistent_translations": n_src, "inconsistent_sources": n_tgt}


def error_rows(segs: list[AuditSegment]) -> list[dict[str, Any]]:
    """One scorecard row per issue and per AI error, in segment order."""
    rows: list[dict[str, Any]] = []
    for s in segs:
        base = {
            "seq": s.seq + 1,
            "segment_id": s.id,
            "source_text": tagged_plain(s.source_tagged),
            "target_text": tagged_plain(s.target_tagged),
        }
        for i in s.issues or []:
            rows.append(
                {
                    **base,
                    "dimension": i["dimension"],
                    "severity": i["mqm_severity"],
                    "span": "",
                    "explanation": f"[{i['code']}] {i['message']}",
                    "source": i["kind"],
                }
            )
        for e in s.mqm_errors or []:
            rows.append(
                {
                    **base,
                    "dimension": e["dimension"],
                    "severity": e["severity"],
                    "span": e.get("span", ""),
                    "explanation": e.get("explanation", ""),
                    "source": "ai",
                }
            )
    return rows


def settings_of(session: Session, audit: Audit) -> dict[str, Any]:
    org = session.get(Organization, audit.org_id)
    out = scorecard.settings_for(org)
    if (audit.settings or {}).get("threshold") is not None:
        out["threshold"] = float(audit.settings["threshold"])
    return out


def finish(session: Session, payload: dict[str, Any]) -> None:
    from arbiter.billing import usage

    audit = _audit(session, payload["audit_id"])
    if audit is None or audit.state != "running":
        return
    segs = list(
        session.execute(
            select(AuditSegment).where(AuditSegment.audit_id == audit.id).order_by(AuditSegment.seq)
        ).scalars()
    )
    summ = dict(audit.summary or {})
    if (audit.settings or {}).get("consistency", True):
        summ["consistency"] = _consistency(segs)
    rows = error_rows(segs)
    card = scorecard.scorecard(rows, audit.word_count, settings_of(session, audit))
    by_code: dict[str, int] = defaultdict(int)
    by_sev: dict[str, int] = defaultdict(int)
    for s in segs:
        for i in s.issues or []:
            by_code[i["code"]] += 1
            by_sev[i["severity"]] += 1
    ai = dict(summ.get("ai") or {"checked": 0, "failed": 0})
    ai["mode"] = (audit.settings or {}).get("ai_mode", "none")
    ai["sample_pct"] = (audit.settings or {}).get("ai_sample_pct")
    units = usage.ai_units("qe", int(ai.get("checked", 0)))
    ai["units"] = str(units)
    summ.update(
        {
            "segments": len(segs),
            "words": audit.word_count,
            "segments_with_issues": sum(1 for s in segs if s.issues or s.mqm_errors),
            "issues_by_code": dict(sorted(by_code.items())),
            "issues_by_severity": dict(by_sev),
            "ai": ai,
            "scorecard": card,
        }
    )
    audit.summary = summ
    audit.ai_units = units
    audit.mqm_score = card["score"]
    audit.verdict = "pass" if card["passed"] else "fail"
    if units > 0:
        usage.record(
            session,
            audit.org_id,
            None,
            "ai_unit",
            units,
            Decimal("0"),
            f"{audit.id}:ai",
            {"step": "audit", "audit_id": audit.id, "segments": int(ai.get("checked", 0))},
        )
    audit.progress = 1.0
    audit.segments_done = audit.segments_total
    audit.finished_at = utcnow()
    transition(audit, "audit", "done")


def retry(session: Session, audit: Audit) -> None:
    """failed -> queued: start over from parsing (a human fixed the cause)."""
    transition(audit, "audit", "queued")
    attempt = _attempt(audit) + 1
    audit.error = None
    audit.progress = 0.0
    audit.segments_done = 0
    audit.mqm_score = None
    audit.verdict = None
    audit.finished_at = None
    audit.summary = {"attempt": attempt}
    session.execute(delete(AuditSegment).where(AuditSegment.audit_id == audit.id))
    enqueue(session, "audit.parse", {"audit_id": audit.id}, idempotency_key=f"{audit.id}:{attempt}:parse")


def counts(session: Session, audit_id: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(AuditSegment).where(AuditSegment.audit_id == audit_id)
        ).scalar_one()
    )


HANDLERS = {"audit.parse": parse, "audit.check": check, "audit.finish": finish}

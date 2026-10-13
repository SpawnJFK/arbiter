"""Translate missing strings: TM -> engine -> glossary -> hard QA -> QE judge -> decide (R-STR-TR-*).

One batch (string_batches) is processed by the worker in chunks of CHUNK translations, each
chunk one work item (kind strings.translate, idempotent per chunk offset), so a big project
never holds one transaction for minutes and the UI can show progress.

Per translation (a key in one target language; plural/array keys run once per form):
  1. placeholders are protected as standalone codes (strings.placeholders)
  2. TM lookup with the key as context: 101 (same key, same source) ships as reviewed when it
     passes QA; 100 is used and still scored; fuzzy matches are engine examples (R-STR-TR-01)
  3. mode tm_only stops here: no TM hit -> the translation stays untranslated
  4. engine from the registry (project setting `engine`, else the platform default)
  5. glossary hits of the frozen-at-batch-start terms; hard QA (quality.checks) on tagged text
     plus string QA (strings.qa) on the restored value
  6. QE judge + quality.qe.decide with the project tier:
       blocked       -> machine, blocked (never released), needs review
       auto_approve  -> reviewed
       senate/review -> machine, needs review
  7. needs review + project setting human_review + org module community -> a review task in the
     reviewer community (strings.review adapter) (R-STR-TR-02)
Every write goes through service.write_translation (versioned, history row).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.contracts import EngineError, MtEngine, MtRequest, SegmentContext, TermHit
from arbiter.engines import tags
from arbiter.engines.registry import available_mt, get_llm, get_mt
from arbiter.errors import Conflict, Invalid
from arbiter.linguistic import glossary as gl
from arbiter.linguistic import tm
from arbiter.models import Organization, StringBatch, StringKey, StringProject, Threshold, utcnow
from arbiter.pipeline.queue import enqueue
from arbiter.quality.checks import run_hard_checks
from arbiter.quality.qe import decide, score_segment
from arbiter.strings import placeholders as ph
from arbiter.strings import plurals, service
from arbiter.strings.qa import check_value

log = logging.getLogger(__name__)
CHUNK = 25
CONTENT_TYPE = "software"
WORK_KIND = "strings.translate"


# ------------------------------------------------------------------ batch lifecycle


def start_batch(
    db: Session,
    proj: StringProject,
    branch: Any,
    langs: list[str] | None,
    *,
    mode: str = "translate",
    key_ids: list[str] | None = None,
    actor: str | None = None,
) -> StringBatch:
    service.writable(branch)
    if mode not in ("translate", "tm_only"):
        raise Invalid("mode must be translate or tm_only")
    langs = [service.norm_locale(lg) for lg in (langs or proj.target_langs)]
    bad = [lg for lg in langs if lg not in proj.target_langs]
    if bad:
        raise Invalid(f"not target languages of this project: {', '.join(bad)}")
    running = db.execute(
        select(StringBatch.id).where(
            StringBatch.project_id == proj.id,
            StringBatch.branch_id == branch.id,
            StringBatch.status.in_(("queued", "running")),
        )
    ).first()
    if running:
        raise Conflict("a translation batch is already running for this branch")
    keys = [
        k
        for k in service.visible_keys(db, proj, branch, include_archived=False)
        if k.translatable and (key_ids is None or k.id in set(key_ids))
    ]
    eff = service.effective(db, branch, [k.id for k in keys], [proj.base_lang, *langs])
    items: list[list[str]] = []
    for k in keys:
        if not service.has_value(eff.get((k.id, proj.base_lang))):
            continue
        for lg in langs:
            if not service.has_value(eff.get((k.id, lg))):
                items.append([k.id, lg])
    batch = StringBatch(
        project_id=proj.id,
        branch_id=branch.id,
        langs=langs,
        mode=mode,
        status="queued" if items else "done",
        total=len(items),
        done=0,
        counts=dict.fromkeys(
            ("tm", "machine", "reviewed", "blocked", "review_tasks", "skipped", "failed"), 0
        ),
        items=items,
        created_by=actor,
        finished_at=None if items else utcnow(),
    )
    db.add(batch)
    db.flush()
    if items:
        enqueue(db, WORK_KIND, {"batch_id": batch.id}, idempotency_key=f"{batch.id}:0")
    return batch


def batch_view(b: StringBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "project_id": b.project_id,
        "branch_id": b.branch_id,
        "langs": b.langs,
        "mode": b.mode,
        "status": b.status,
        "total": b.total,
        "done": b.done,
        "progress": round(100 * b.done / b.total) if b.total else 100,
        "counts": b.counts,
        "review_job_id": b.review_job_id,
        "error": b.error,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
    }


def process(db: Session, payload: dict[str, Any]) -> None:
    """Worker handler for strings.translate: one chunk, then re-enqueue the next."""
    batch = db.get(StringBatch, payload["batch_id"], with_for_update=True)
    if batch is None or batch.status in ("done", "failed"):
        return
    proj = db.get(StringProject, batch.project_id)
    if proj is None:
        batch.status, batch.error = "failed", "project deleted"
        return
    branch = service.get_branch(db, proj, batch.branch_id)
    batch.status = "running"
    start = batch.done
    chunk = (batch.items or [])[start : start + CHUNK]
    run = Runner(db, proj, branch, batch)
    counts = dict(batch.counts or {})
    for key_id, lang in chunk:
        try:
            outcome = run.one(key_id, lang)
        except EngineError as e:
            log.warning("strings batch %s: %s [%s] failed: %s", batch.id, key_id, lang, e)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    counts["review_tasks"] = counts.get("review_tasks", 0) + run.review_tasks
    batch.counts = counts
    batch.done = start + len(chunk)
    if batch.done >= batch.total:
        batch.status = "done"
        batch.finished_at = utcnow()
        batch.items = []
    else:
        enqueue(db, WORK_KIND, {"batch_id": batch.id}, idempotency_key=f"{batch.id}:{batch.done}")
    db.flush()


def run_inline(db: Session, batch: StringBatch) -> StringBatch:
    """Process a whole batch in this transaction (tests and the CLI)."""
    while batch.status not in ("done", "failed"):
        process(db, {"batch_id": batch.id})
        db.refresh(batch)
    return batch


# ------------------------------------------------------------------ one translation


@dataclass
class Piece:
    form: str | None  # None for a plain string
    source: str
    protected: ph.Protected
    target_tagged: str | None = None
    origin: str = "mt"
    engine: str | None = None
    tm_kind: str | None = None
    hits: list[TermHit] = field(default_factory=list)


class Runner:
    def __init__(self, db: Session, proj: StringProject, branch: Any, batch: StringBatch | None) -> None:
        self.db, self.proj, self.branch, self.batch = db, proj, branch, batch
        self.org = db.get(Organization, proj.org_id)
        self.settings = service.settings_of(proj)
        self.style = self.settings["placeholder_style"]
        self.review_tasks = 0
        self._terms: dict[str, list[Any]] = {}
        self._engines: list[MtEngine] | None = None
        self._thresholds: dict[str, tuple[float, float, float, bool]] = {}

    # -- dependencies, resolved lazily so tm_only batches never touch engines
    def terms(self, lang: str) -> list[Any]:
        if lang not in self._terms:
            self._terms[lang] = gl.active_terms(
                self.db, self.proj.org_id, self.proj.base_lang, lang, CONTENT_TYPE
            )
        return self._terms[lang]

    def engines(self) -> list[MtEngine]:
        if self._engines is None:
            names = available_mt()
            want = self.settings.get("engine") or get_settings().default_mt_engine
            ordered = ([want] if want in names else []) + [n for n in names if n != want]
            if not get_settings().is_test and not str(want).startswith("mock"):
                ordered = [n for n in ordered if "mock" not in n]
            self._engines = []
            for n in ordered:
                try:
                    self._engines.append(get_mt(n))
                except EngineError as e:
                    log.warning("engine %s skipped: %s", n, e)
            if not self._engines:
                raise EngineError("no MT engine available")
        return self._engines

    def threshold(self, lang: str) -> tuple[float, float, float, bool]:
        if lang not in self._thresholds:
            rows = (
                self.db.execute(
                    select(Threshold).where(
                        Threshold.org_id == self.proj.org_id, Threshold.content_type == CONTENT_TYPE
                    )
                )
                .scalars()
                .all()
            )
            row = next((t for t in rows if t.target_lang == lang), None) or next(
                (t for t in rows if t.target_lang is None), None
            )
            s = get_settings()
            self._thresholds[lang] = (
                (row.value, row.band_width, row.safety_offset, row.auto_approval_suspended)
                if row
                else (s.default_threshold, s.band_width, 0.0, False)
            )
        return self._thresholds[lang]

    # -- the work
    def pieces(self, key: StringKey, base: Any, lang: str) -> list[Piece]:
        if key.kind == "string":
            return [Piece(None, base, ph.protect(base, self.style))]
        forms = base if isinstance(base, dict) else {"other": str(base)}
        if key.kind == "array":
            return [Piece(i, t, ph.protect(t, self.style)) for i, t in forms.items()]
        out = []
        explicit = [f for f in forms if f.startswith("=")]
        for cat in [*explicit, *plurals.categories(lang, self.settings["plural_rules"])]:
            src_form = plurals.source_form_for(cat, forms)
            if src_form is not None:
                out.append(Piece(cat, forms[src_form], ph.protect(forms[src_form], self.style)))
        return out

    def one(self, key_id: str, lang: str) -> str:
        db, proj = self.db, self.proj
        key = db.get(StringKey, key_id)
        if key is None or key.archived_at is not None or not key.translatable:
            return "skipped"
        eff = service.effective(db, self.branch, [key.id], [proj.base_lang, lang])
        if service.has_value(eff.get((key.id, lang))):
            return "skipped"  # filled meanwhile (human edit, import)
        base = service.value_of(eff.get((key.id, proj.base_lang)))
        if base is None:
            return "skipped"
        pieces = self.pieces(key, base, lang)
        terms = self.terms(lang)
        to_engine: list[tuple[Piece, MtRequest]] = []
        for p in pieces:
            p.hits = gl.find_source_terms(tags.plain(p.protected.tagged), terms, proj.base_lang)
            matches = tm.lookup(
                db,
                proj.org_id,
                proj.base_lang,
                lang,
                p.protected.tagged,
                context_hash=context_hash(key, p.form),
            )
            best = matches[0] if matches else None
            if best is not None and best.kind in ("context", "exact"):
                p.target_tagged, p.origin, p.tm_kind, p.engine = best.target_tagged, "tm", best.kind, None
                continue
            if self.batch is not None and self.batch.mode == "tm_only":
                return "skipped"
            to_engine.append(
                (
                    p,
                    MtRequest(
                        source_tagged=p.protected.tagged,
                        source_lang=proj.base_lang,
                        target_lang=lang,
                        terms=p.hits,
                        context_before=_context(key, p.form),
                        max_length=key.max_length if key.kind != "plural" else None,
                        tm_examples=[m for m in matches if m.kind == "fuzzy"][:2],
                    ),
                )
            )
        if to_engine:
            results = self.translate([r for _, r in to_engine])
            for (p, _), res in zip(to_engine, results, strict=True):
                p.target_tagged, p.engine, p.origin = res.target_tagged or "", res.engine, "mt"
        return self.finish(key, lang, base, pieces)

    def translate(self, reqs: list[MtRequest]) -> list[Any]:
        engines = self.engines()
        results = engines[0].translate(reqs)
        for i, res in enumerate(results):
            if res.error or not res.target_tagged:
                for alt in engines[1:]:
                    r2 = alt.translate([reqs[i]])[0]
                    if not r2.error and r2.target_tagged:
                        results[i] = r2
                        break
        return results

    def finish(self, key: StringKey, lang: str, base: Any, pieces: list[Piece]) -> str:
        db, proj = self.db, self.proj
        issues: list[dict[str, Any]] = []
        scores: list[float | None] = []
        decisions: list[str] = []
        values: dict[str, str] = {}
        all_context = all(p.tm_kind == "context" for p in pieces)
        judge = None
        for p in pieces:
            tagged = p.target_tagged or ""
            try:
                restored = ph.restore(tagged, p.protected.codes)
            except ph.TaggedParseError:
                restored = tags.plain(tagged)
            values[p.form or ""] = restored
            ctx = SegmentContext(
                segment_id=f"{key.id}:{lang}:{p.form or ''}",
                source_tagged=p.protected.tagged,
                target_tagged=tagged,
                source_lang=proj.base_lang,
                target_lang=lang,
                content_type=CONTENT_TYPE,
                terms=p.hits,
                context_before=_context(key, p.form),
                max_length=key.max_length if key.kind == "string" else None,
            )
            violations = gl.check_target(tags.plain(tagged), p.hits, lang)
            hard = run_hard_checks(ctx, violations)
            for h in hard:
                if h.severity != "info":
                    issues.append(
                        {"code": h.code, "severity": h.severity, "message": h.message, "blocking": h.blocking}
                        | ({"form": p.form} if p.form is not None else {})
                    )
            if any(h.blocking for h in hard):
                scores.append(0.0)
                decisions.append("blocked")
                continue
            if p.tm_kind == "context":
                scores.append(100.0)
                decisions.append("auto_approve")
                continue
            judge = judge or get_llm(get_settings().default_judge_engine)
            try:
                qe = score_segment(ctx, judge, violations)
                score: float | None = qe.score
            except EngineError:
                score = None
            thr, band, offset, suspended = self.threshold(lang)
            scores.append(score)
            decisions.append(
                decide(
                    score,
                    hard,
                    thr,
                    band,
                    tier=proj.tier,
                    regulated=bool(self.org and self.org.regulated),
                    safety_offset=offset,
                    suspended=suspended,
                )
            )
        value: Any = (
            values.get("", "")
            if key.kind == "string"
            else plurals.sort_forms(values)
            if key.kind == "plural"
            else values
        )
        str_issues = check_value(
            key, base, value, lang, style=self.style, rules=self.settings["plural_rules"]
        )
        seen = {(i["code"], i.get("form"), i["message"]) for i in issues}
        issues += [i for i in str_issues if (i["code"], i.get("form"), i["message"]) not in seen]
        blocked = any(i["blocking"] for i in issues)
        if blocked:
            decision = "blocked"
        elif all(d == "auto_approve" for d in decisions):
            decision = "auto_approve"
        elif "review" in decisions:
            decision = "review"
        else:
            decision = "senate"
        known = [s for s in scores if s is not None]
        qe_score = min(known) if known else None
        state = "reviewed" if decision == "auto_approve" else "machine"
        origin = "tm" if all(p.origin == "tm" for p in pieces) else "mt"
        engine = next((p.engine for p in pieces if p.engine), None)
        res = service.write_translation(
            db,
            proj,
            self.branch,
            key,
            lang,
            value,
            state=state,
            origin=origin,
            event="tm" if origin == "tm" else "machine",
            actor_type="system" if origin == "tm" else "engine",
            actor_id=engine or "tm",
            engine=engine,
            qe_score=qe_score,
            qa=issues,
            blocked=blocked,
            needs_review=decision != "auto_approve",
            decision=decision,
            tm=[p.tm_kind for p in pieces if p.tm_kind],
            context_match=all_context,
        )
        if decision != "auto_approve" and self.settings.get("human_review"):
            from arbiter.strings import review

            n = review.request_review(
                db, proj, self.branch, key, res.tr, lang, pieces=pieces, batch=self.batch
            )
            self.review_tasks += n
        if blocked:
            return "blocked"
        if origin == "tm":
            return "tm"
        return "reviewed" if state == "reviewed" else "machine"


def context_hash(key: StringKey, form: str | None) -> str:
    """TM context for strings: the key (and form) itself, so a 101 match means same key, same source."""
    return tm.context_hash(f"{key.namespace}:{key.name}#{form or ''}", None)


def _context(key: StringKey, form: str | None) -> str:
    parts = [f"UI string key: {key.name}"]
    if key.description:
        parts.append(key.description)
    if form is not None and key.kind == "plural":
        parts.append(f"plural form: {form}")
    return " | ".join(parts)


def translate_one(db: Session, proj: StringProject, branch: Any, key: StringKey, lang: str) -> str:
    """Machine-translate one key now (the editor's "suggest" button). Overwrites nothing filled."""
    return Runner(db, proj, branch, None).one(key.id, lang)


def store_tm(
    db: Session, proj: StringProject, key: StringKey, lang: str, base: Any, value: Any, origin: str
) -> None:
    """Human-approved values go into the org TM per form (R-TM-01), keyed by the key context."""
    style = service.settings_of(proj)["placeholder_style"]
    if key.kind == "string":
        pairs = [(None, base, value)] if isinstance(base, str) and isinstance(value, str) else []
    else:
        bf = base if isinstance(base, dict) else {}
        vf = value if isinstance(value, dict) else {}
        pairs = []
        for form, text in vf.items():
            src_form = plurals.source_form_for(form, bf) if key.kind == "plural" else form
            if src_form in bf and text:
                pairs.append((form, bf[src_form], text))
    for form, src, tgt in pairs:
        if not src.strip() or not tgt.strip():
            continue
        sp = ph.protect(src, style)
        tp = _protect_like(tgt, sp, style)
        if tp is None:
            continue
        tm.store(
            db,
            proj.org_id,
            proj.base_lang,
            lang,
            sp.tagged,
            tp,
            content_type=CONTENT_TYPE,
            context_hash=context_hash(key, form),
            origin=origin,
        )


def _protect_like(target: str, source: ph.Protected, style: str) -> str | None:
    """Tag a target with the SOURCE's code ids (same placeholder text -> same id), or None."""
    tp = ph.protect(target, style)
    ids: list[str] = []
    pool = {i + 1: c for i, c in enumerate(source.codes)}
    used: set[int] = set()
    for code in tp.codes:
        match = next((i for i, c in pool.items() if c == code and i not in used), None)
        if match is None:
            return None
        used.add(match)
        ids.append(str(match))
    out = tp.tagged
    for n, real in sorted(enumerate(ids, start=1), reverse=True):
        out = out.replace(f"⟦{n}/⟧", f"\x00{real}\x01")
    return out.replace("\x00", "⟦").replace("\x01", "/⟧")

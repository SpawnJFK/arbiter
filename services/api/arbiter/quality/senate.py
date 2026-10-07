"""The senate: independent multi-role review, best-of-N translation, and QA triage.

Review senate (``review_senate``)
---------------------------------
Four roles look at the same segment with different information, on purpose:
    accuracy     source + target (+ context, terms). Should be the strongest model.
    fluency      target ONLY. Never receives source text or source context, so it judges
                 the text as a native reader would and cannot be anchored by the source.
    terminology  source + target + glossary terms (with kinds) + style rules + TM matches.
    consistency  source + target + the other (source, target) pairs of the document.
Roles run independently and concurrently (no debate: debate converges on the most
confident voice, not the right one) and each may use its own LlmClient.

Arbitration:
    * Findings are normalised (judge.parse_errors) and located on the target text.
    * Two findings overlap when their target character ranges overlap and their
      dimensions are compatible (same dimension, or a pair in COMPATIBLE). Two omissions
      (no span) overlap when they share the dimension.
    * A cluster raised by 2+ distinct roles is CONFIRMED; its severity is the median of
      the members (upper median on even counts: when two independent reviewers disagree on
      severity we take the more cautious one).
    * A lone finding (one role) that is minor style or neutral is DISCARDED (cheap noise).
    * Any other lone finding is VERIFIED (MQM-APE style): the accuracy client is asked
      whether fixing that span improves the translation; confirmed only on "yes". If the
      verification call itself fails, the finding is kept (fail safe: doubt goes to review).
    * If fewer than ``min_roles`` roles answered, the verdict is VOID: no score; the caller
      must route to a human or raise the safety offset. A partial panel is not a senate.
    * score = mqm_score(confirmed, source word count).

Translation senate (``translation_senate``)
-------------------------------------------
Best-of-N: every engine translates; candidates are filtered by hard checks and glossary
adherence FIRST (a candidate with a blocking issue is out, and among survivors fewer term
violations beats a higher judge score), then judged; the winner is the highest score, ties
broken by engine order. Glossary first because a client-mandated term is a contract, while
a judge score is an estimate.

Triage (``triage``)
-------------------
A model labels NON-blocking QA warnings as "real" or "false_positive". Blocking issues
are returned as "real" by rule and never shown to the model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

from arbiter.contracts import (
    EngineError,
    LlmClient,
    MqmError,
    MtEngine,
    MtRequest,
    QaIssue,
    SegmentContext,
    SenateVerdict,
    TermViolation,
    Usage,
)
from arbiter.engines import tags
from arbiter.quality.checks import run_hard_checks
from arbiter.quality.judge import judge, parse_errors, versioned
from arbiter.quality.mqm import evaluation_word_count, mqm_score
from arbiter.quality.prompts import ERRORS_SCHEMA, SENATE_ROLE_SYSTEM, TRIAGE_SYSTEM, VERIFY_SYSTEM, payload

ROLES: tuple[str, ...] = ("accuracy", "fluency", "terminology", "consistency")
SEVERITY_ORDER = ("neutral", "minor", "major", "critical")
COMPATIBLE: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"accuracy", "terminology"}),
        frozenset({"linguistic_conventions", "style"}),
        frozenset({"style", "audience_appropriateness"}),
        frozenset({"linguistic_conventions", "locale_conventions"}),
    }
)
LONE_DISCARD_DIMENSIONS = frozenset({"style"})


def compatible(a: str, b: str) -> bool:
    return a == b or frozenset({a, b}) in COMPATIBLE


def add_usage(total: Usage, u: Usage) -> None:
    total.input_tokens += u.input_tokens
    total.output_tokens += u.output_tokens
    total.characters += u.characters
    total.cost += u.cost


# ----------------------------------------------------------------- prompts per role


def build_role_prompt(role: str, ctx: SegmentContext) -> tuple[str, str]:
    """Role-specific view of the segment. The fluency view contains no source text."""
    src, tgt = tags.plain(ctx.source_tagged), tags.plain(ctx.target_tagged)
    common = {"role": role, "target_lang": ctx.target_lang, "content_type": ctx.content_type, "target": tgt}
    if role == "fluency":
        data: dict[str, Any] = common
    elif role == "accuracy":
        data = {
            **common,
            "source_lang": ctx.source_lang,
            "source": src,
            "context_before": ctx.context_before,
            "context_after": ctx.context_after,
            "terms": [{"source": t.source_term, "target": t.target_term, "kind": t.kind} for t in ctx.terms],
        }
    elif role == "terminology":
        data = {
            **common,
            "source_lang": ctx.source_lang,
            "source": src,
            "terms": [
                {"source": t.source_term, "target": t.target_term, "kind": t.kind, "note": t.note}
                for t in ctx.terms
            ],
            "style_rules": ctx.style_rules,
            "tm_matches": [
                {
                    "source": tags.plain(m.source_tagged),
                    "target": tags.plain(m.target_tagged),
                    "score": m.score,
                }
                for m in ctx.tm_matches
            ],
        }
    elif role == "consistency":
        data = {
            **common,
            "source_lang": ctx.source_lang,
            "source": src,
            "document": [{"source": tags.plain(s), "target": tags.plain(t)} for s, t in ctx.document_targets],
        }
    else:
        raise ValueError(f"unknown senate role {role!r}")
    return SENATE_ROLE_SYSTEM[role], payload("senate_role", **data)


# ----------------------------------------------------------------- arbitration


@dataclass
class _Finding:
    role: str
    error: MqmError
    start: int | None  # None = omission / not located
    end: int | None


def _locate(span: str, target: str) -> tuple[int | None, int | None]:
    if not span.strip():
        return None, None
    i = target.casefold().find(span.casefold())
    if i < 0:
        # whitespace-normalised fallback: approximate position by the first word
        first = span.split()[0].casefold() if span.split() else ""
        i = target.casefold().find(first) if first else -1
        if i < 0:
            return None, None
        return i, i + len(span)
    return i, i + len(span)


def _overlap(a: _Finding, b: _Finding) -> bool:
    if not compatible(a.error.dimension, b.error.dimension):
        return False
    if a.start is None or b.start is None:
        return a.start is None and b.start is None and a.error.dimension == b.error.dimension
    assert a.end is not None and b.end is not None
    return a.start < b.end and b.start < a.end


def _clusters(findings: list[_Finding]) -> list[list[_Finding]]:
    parent = list(range(len(findings)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            if _overlap(findings[i], findings[j]):
                parent[root(i)] = root(j)
    groups: dict[int, list[_Finding]] = {}
    for i, f in enumerate(findings):
        groups.setdefault(root(i), []).append(f)
    return sorted(
        groups.values(), key=lambda g: min(ROLES.index(f.role) if f.role in ROLES else 99 for f in g)
    )


def _merge(cluster: list[_Finding]) -> MqmError:
    sevs = sorted((f.error.severity for f in cluster), key=SEVERITY_ORDER.index)
    median = sevs[len(sevs) // 2]
    dims = [f.error.dimension for f in cluster]
    dim = max(dims, key=lambda d: (dims.count(d), -dims.index(d)))
    rep = next((f for f in cluster if f.error.severity == median), cluster[0])
    roles = sorted({f.role for f in cluster}, key=lambda r: ROLES.index(r) if r in ROLES else 99)
    return MqmError(
        dim, median, rep.error.span, rep.error.explanation, role="+".join(roles), fix=rep.error.fix
    )  # type: ignore[arg-type]


def verify_finding(ctx: SegmentContext, error: MqmError, llm: LlmClient) -> tuple[bool, Usage, str]:
    """Ask whether fixing this span improves the translation. Returns (yes, usage, reason)."""
    user = payload(
        "verify",
        source_lang=ctx.source_lang,
        target_lang=ctx.target_lang,
        source=tags.plain(ctx.source_tagged),
        target=tags.plain(ctx.target_tagged),
        span=error.span,
        dimension=error.dimension,
        severity=error.severity,
        explanation=error.explanation,
        fix=error.fix,
    )
    data, usage, _model = llm.complete_json(
        VERIFY_SYSTEM, user, schema_hint='{"improves": bool, "reason": str}'
    )
    improves = data.get("improves")
    if isinstance(improves, str):
        improves = improves.strip().lower() in ("yes", "true")
    return bool(improves), usage, str(data.get("reason", ""))


def _resolve_clients(
    clients: LlmClient | Mapping[str, LlmClient], roles: Sequence[str]
) -> dict[str, LlmClient]:
    if isinstance(clients, Mapping):
        default = clients.get("default") or clients.get("accuracy") or next(iter(clients.values()))
        resolved = {r: clients.get(r, default) for r in roles}
        resolved["verify"] = clients.get("verify") or clients.get("accuracy") or default
        return resolved
    return {r: clients for r in (*roles, "verify")}


def review_senate(
    ctx: SegmentContext,
    clients: LlmClient | Mapping[str, LlmClient],
    *,
    min_roles: int = 3,
    roles: Sequence[str] = ROLES,
) -> SenateVerdict:
    """Independent review by every role, then arbitration (see module docstring).

    ``clients`` is one LlmClient for all roles, or a mapping role -> client with optional
    "default" and "verify" keys (verification defaults to the accuracy client).
    """
    by_role = _resolve_clients(clients, roles)
    target = tags.plain(ctx.target_tagged)
    usage = Usage()
    findings: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, Any]] = []

    def run(role: str) -> tuple[str, list[MqmError] | None, Usage, str]:
        system, user = build_role_prompt(role, ctx)
        try:
            data, u, _model = by_role[role].complete_json(system, user, schema_hint=ERRORS_SCHEMA)
            errs, _dropped = parse_errors(data, target, role=role, allow_omission=role == "accuracy")
            return role, errs, u, ""
        except EngineError as e:
            return role, None, Usage(), str(e)

    with ThreadPoolExecutor(max_workers=max(1, len(roles))) as pool:
        results = list(pool.map(run, roles))

    answered: list[_Finding] = []
    n_answered = 0
    for role, errs, u, err in results:
        add_usage(usage, u)
        if errs is None:
            failures.append({"role": role, "error": err})
            continue
        n_answered += 1
        findings[role] = [asdict(e) for e in errs]
        for e in errs:
            s, t = _locate(e.span, target)
            answered.append(_Finding(role, e, s, t))
    if failures:
        findings["_failed"] = failures

    if n_answered < min_roles:
        return SenateVerdict(
            purpose="review",
            roles_answered=n_answered,
            roles_total=len(roles),
            findings=findings,
            confirmed=[],
            discarded=[],
            score=None,
            outcome="void",
            usage=usage,
        )

    confirmed: list[MqmError] = []
    discarded: list[MqmError] = []
    to_verify: list[MqmError] = []
    for cluster in _clusters(answered):
        merged = _merge(cluster)
        if len({f.role for f in cluster}) >= 2:
            confirmed.append(merged)
        elif merged.severity == "neutral" or (
            merged.severity == "minor" and merged.dimension in LONE_DISCARD_DIMENSIONS
        ):
            discarded.append(merged)
        else:
            to_verify.append(merged)

    verifications: list[dict[str, Any]] = []
    if to_verify:

        def check(e: MqmError) -> tuple[MqmError, bool, Usage, str]:
            try:
                yes, u, reason = verify_finding(ctx, e, by_role["verify"])
                return e, yes, u, reason
            except EngineError as ex:
                return e, True, Usage(), f"verification failed, kept: {ex}"

        with ThreadPoolExecutor(max_workers=min(8, len(to_verify))) as pool:
            for e, yes, u, reason in pool.map(check, to_verify):
                add_usage(usage, u)
                verifications.append({"span": e.span, "role": e.role, "improves": yes, "reason": reason})
                (confirmed if yes else discarded).append(e)
        findings["_verifications"] = verifications

    score = mqm_score(confirmed, evaluation_word_count(tags.plain(ctx.source_tagged), ctx.source_lang))
    return SenateVerdict(
        purpose="review",
        roles_answered=n_answered,
        roles_total=len(roles),
        findings=findings,
        confirmed=confirmed,
        discarded=discarded,
        score=score,
        outcome="errors_confirmed" if confirmed else "clean",
        usage=usage,
    )


# ----------------------------------------------------------------- translation senate


def _ctx_from_request(req: MtRequest, target: str, segment_id: str = "candidate") -> SegmentContext:
    return SegmentContext(
        segment_id=segment_id,
        source_tagged=req.source_tagged,
        target_tagged=target,
        source_lang=req.source_lang,
        target_lang=req.target_lang,
        terms=list(req.terms),
        style_rules=list(req.style_rules),
        tm_matches=list(req.tm_examples),
        context_before=req.context_before,
        context_after=req.context_after,
        max_length=req.max_length,
    )


def translation_senate(
    req: MtRequest,
    engines: Sequence[MtEngine],
    judge_clients: LlmClient | Sequence[LlmClient],
    term_checker: Callable[[str], list[TermViolation]],
) -> SenateVerdict:
    """Best-of-N translation. ``term_checker`` receives the candidate target (tagged) and
    returns its glossary violations. Outcome "winner:<engine>" or "void" when no candidate
    survives the hard checks (the segment then needs a human translator/reviewer)."""
    judges = [judge_clients] if not isinstance(judge_clients, Sequence) else list(judge_clients)
    usage = Usage()
    candidates: list[dict[str, Any]] = []

    for order, engine in enumerate(engines):
        try:
            res = engine.translate([req])[0]
        except EngineError as e:
            candidates.append({"engine": engine.name, "order": order, "error": str(e), "eliminated": True})
            continue
        add_usage(usage, res.usage)
        if res.error:
            candidates.append({"engine": engine.name, "order": order, "error": res.error, "eliminated": True})
            continue
        violations = term_checker(res.target_tagged)
        ctx = _ctx_from_request(req, res.target_tagged, f"candidate:{engine.name}")
        hard = run_hard_checks(ctx, violations)
        candidates.append(
            {
                "engine": engine.name,
                "order": order,
                "target": res.target_tagged,
                "model_version": res.model_version,
                "hard": [i.code for i in hard if i.blocking],
                "term_violations": len(violations),
                "eliminated": any(i.blocking for i in hard),
                "_ctx": ctx,
                "_violations": violations,
            }
        )

    survivors = [c for c in candidates if not c["eliminated"]]

    def score_one(job: tuple[dict[str, Any], LlmClient]) -> tuple[str, float | None, list[MqmError], Usage]:
        cand, client = job
        try:
            qe = judge(cand["_ctx"], client, cand["_violations"])
            return cand["engine"], qe.score, qe.errors, qe.usage
        except EngineError:
            return cand["engine"], None, [], Usage()

    jobs = [(c, j) for c in survivors for j in judges]
    scores: dict[str, list[float]] = {}
    errors_of: dict[str, list[MqmError]] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
            for name, score, errs, u in pool.map(score_one, jobs):
                add_usage(usage, u)
                if score is not None:
                    scores.setdefault(name, []).append(score)
                    errors_of.setdefault(name, errs)
    for c in survivors:
        s = scores.get(c["engine"])
        c["score"] = round(sum(s) / len(s), 2) if s else None

    public = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
    ranked = sorted(
        survivors,
        key=lambda c: (c["term_violations"], c["score"] is None, -(c["score"] or 0.0), c["order"]),
    )
    if not ranked:
        return SenateVerdict(
            purpose="translation",
            roles_answered=0,
            roles_total=len(engines),
            findings={"candidates": public},
            confirmed=[],
            discarded=[],
            score=None,
            outcome="void",
            usage=usage,
        )
    win = ranked[0]
    return SenateVerdict(
        purpose="translation",
        roles_answered=sum(1 for c in candidates if "target" in c),
        roles_total=len(engines),
        findings={"candidates": public},
        confirmed=errors_of.get(win["engine"], []),
        discarded=[],
        score=win["score"],
        outcome=f"winner:{win['engine']}",
        winner_target=win["target"],
        usage=usage,
    )


# ----------------------------------------------------------------- triage


def triage(ctx: SegmentContext, issues: list[QaIssue], llm: LlmClient) -> list[dict[str, Any]]:
    """Label QA issues real/false_positive. Blocking issues are "real" by rule; a model
    failure or a missing label leaves a warning "real" (fail safe)."""
    out: list[dict[str, Any]] = []
    candidates: list[tuple[int, QaIssue]] = []
    for i, iss in enumerate(issues):
        base = {
            "id": i,
            "code": iss.code,
            "severity": iss.severity,
            "message": iss.message,
            "blocking": iss.blocking,
        }
        if iss.blocking:
            out.append(
                {
                    **base,
                    "label": "real",
                    "reason": "blocking checks cannot be cleared by a model",
                    "by": "rule",
                }
            )
        else:
            out.append({**base, "label": "real", "reason": "not triaged", "by": "rule"})
            candidates.append((i, iss))
    if not candidates:
        return out
    user = payload(
        "triage",
        source_lang=ctx.source_lang,
        target_lang=ctx.target_lang,
        source=tags.plain(ctx.source_tagged),
        target=tags.plain(ctx.target_tagged),
        warnings=[{"id": i, "code": iss.code, "message": iss.message} for i, iss in candidates],
    )
    try:
        data, _usage, model = llm.complete_json(TRIAGE_SYSTEM, user)
    except EngineError as e:
        for i, _ in candidates:
            out[i]["reason"] = f"triage unavailable: {e}"
        return out
    allowed = {i for i, _ in candidates}
    for lab in data.get("labels") or []:
        if not isinstance(lab, dict):
            continue
        try:
            idx = int(lab.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if idx not in allowed:
            continue  # the model can never touch a blocking issue, even by naming its id
        label = lab.get("label")
        if label in ("real", "false_positive"):
            out[idx].update(label=label, reason=str(lab.get("reason", "")), by=versioned(model))
    return out

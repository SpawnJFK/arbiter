"""LLM judge: GEMBA-MQM style error annotation -> MQM score.

Order of operations, and why:
1. Hard checks run first. Any blocking issue -> score 0 and the LLM is NOT called: the
   segment cannot ship anyway, so a model call would cost money and could only add a
   misleadingly high number.
2. The model annotates errors (dimension, severity, span). The rubric says explicitly that
   "no errors" is a valid answer; LLM judges over-flag when asked to "find errors".
3. Output is validated: unknown dimensions/severities are mapped or dropped, and any span
   that does not occur in the target is dropped as hallucinated, except omissions (the
   missing words are by definition not in the target).
4. Score = mqm_score(errors, source word count), see mqm.py.

The judge sees plain text (codes removed): tag integrity is a deterministic check, and
spans without codes are what a reviewer sees highlighted.
"""

from __future__ import annotations

import re
from typing import Any

from arbiter.contracts import (
    MQM_DIMENSIONS,
    EngineError,
    LlmClient,
    MqmError,
    QeResult,
    SegmentContext,
    TermViolation,
    Usage,
)
from arbiter.engines import tags
from arbiter.quality.checks import blocking, run_hard_checks
from arbiter.quality.mqm import evaluation_word_count, mqm_score
from arbiter.quality.prompts import ERRORS_SCHEMA, JUDGE_SYSTEM, PROMPT_VERSION, payload

DIMENSION_ALIASES = {
    "fluency": "linguistic_conventions",
    "grammar": "linguistic_conventions",
    "spelling": "linguistic_conventions",
    "punctuation": "linguistic_conventions",
    "linguistic": "linguistic_conventions",
    "mistranslation": "accuracy",
    "omission": "accuracy",
    "addition": "accuracy",
    "untranslated": "accuracy",
    "terms": "terminology",
    "term": "terminology",
    "locale": "locale_conventions",
    "locale_convention": "locale_conventions",
    "audience": "audience_appropriateness",
    "markup": "design_and_markup",
    "design": "design_and_markup",
    "register": "style",
}
SEVERITIES = ("neutral", "minor", "major", "critical")


def _norm_dimension(value: Any) -> str | None:
    """Map "Accuracy/Mistranslation", "fluency", "Terminology" ... onto MQM_DIMENSIONS."""
    d = re.sub(r"[\s/-]+", "_", str(value or "").strip().lower())
    for cand in (d, d.split("_")[0], d.split("_")[-1]):
        cand = DIMENSION_ALIASES.get(cand, cand)
        if cand in MQM_DIMENSIONS:
            return cand
    return None


def _norm_severity(value: Any) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in SEVERITIES else None


def _norm_ws(s: str) -> str:
    return " ".join(s.split()).casefold()


def span_in_target(span: str, target_plain: str) -> bool:
    return bool(span.strip()) and _norm_ws(span) in _norm_ws(target_plain)


def parse_errors(
    data: dict[str, Any], target_plain: str, *, role: str, allow_omission: bool = True
) -> tuple[list[MqmError], list[dict[str, Any]]]:
    """Validate model output. Returns (kept errors, dropped items with a reason)."""
    raw = data.get("errors")
    if not isinstance(raw, list):
        raise EngineError(f"{role}: output has no 'errors' list")
    kept: list[MqmError] = []
    dropped: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            dropped.append({"item": item, "reason": "not an object"})
            continue
        dim = _norm_dimension(item.get("dimension"))
        sev = _norm_severity(item.get("severity"))
        span = str(item.get("span") or "")
        explanation = str(item.get("explanation") or "")
        category = str(item.get("category") or "").lower()
        if dim is None or sev is None:
            dropped.append({"item": item, "reason": "unknown dimension or severity"})
            continue
        is_omission = "omission" in category or (
            dim == "accuracy" and explanation.lower().startswith(("omission", "omitted", "missing"))
        )
        if not span_in_target(span, target_plain):
            if is_omission and allow_omission:
                span = ""
            else:
                dropped.append({"item": item, "reason": "span not found in target (hallucinated)"})
                continue
        fix = item.get("fix")
        kept.append(MqmError(dim, sev, span, explanation, role=role, fix=None if fix is None else str(fix)))  # type: ignore[arg-type]
    return kept, dropped


def build_judge_prompt(ctx: SegmentContext) -> tuple[str, str]:
    user = payload(
        "judge",
        source_lang=ctx.source_lang,
        target_lang=ctx.target_lang,
        content_type=ctx.content_type,
        source=tags.plain(ctx.source_tagged),
        target=tags.plain(ctx.target_tagged),
        terms=[{"source": t.source_term, "target": t.target_term, "kind": t.kind} for t in ctx.terms],
        style_rules=ctx.style_rules,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
    )
    return JUDGE_SYSTEM, user


def versioned(model_version: str) -> str:
    return f"{model_version}+prompt:{PROMPT_VERSION}"


def judge(
    ctx: SegmentContext, llm: LlmClient, term_violations: list[TermViolation] | None = None
) -> QeResult:
    """Score one segment. Raises EngineError when the model fails (caller routes to a human)."""
    hard = run_hard_checks(ctx, term_violations)
    if blocking(hard):
        return QeResult(score=0.0, errors=[], hard_issues=hard, model_version="hard-checks", usage=Usage())
    system, user = build_judge_prompt(ctx)
    data, usage, model = llm.complete_json(system, user, schema_hint=ERRORS_SCHEMA)
    errors, _dropped = parse_errors(data, tags.plain(ctx.target_tagged), role="judge")
    score = mqm_score(errors, evaluation_word_count(tags.plain(ctx.source_tagged), ctx.source_lang))
    return QeResult(score=score, errors=errors, hard_issues=hard, model_version=versioned(model), usage=usage)

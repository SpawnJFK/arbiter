"""AI post-editor for the ai_review tier.

The editor applies confirmed senate errors with minimal edits. It is the only place a
model writes target text after MT, so it is fenced in:
  * only the ai_review tier may use it (hybrid/full have a paid human for this);
  * the result must keep exactly the same code tokens as the original target;
  * mandatory/DNT terms present before the edit must still be present after it;
  * hard checks are re-run and the edit is rejected if it introduces any blocking issue
    that the original did not have.
A rejected edit returns the ORIGINAL target unchanged: an untouched segment with known
errors is safer than a "fixed" one that broke markup or terminology.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import replace

from arbiter.contracts import EngineError, LlmClient, MqmError, SegmentContext, TermViolation, Usage
from arbiter.engines import tags
from arbiter.quality.checks import run_hard_checks
from arbiter.quality.prompts import EDITOR_SYSTEM, payload

log = logging.getLogger(__name__)


def build_editor_prompt(ctx: SegmentContext, errors: list[MqmError]) -> tuple[str, str]:
    user = payload(
        "edit",
        source_lang=ctx.source_lang,
        target_lang=ctx.target_lang,
        source=ctx.source_tagged,
        target=ctx.target_tagged,
        errors=[
            {
                "dimension": e.dimension,
                "severity": e.severity,
                "span": e.span,
                "explanation": e.explanation,
                "fix": e.fix,
            }
            for e in errors
        ],
        terms=[
            {"source": t.source_term, "target": t.target_term, "kind": t.kind}
            for t in ctx.terms
            if t.kind in ("mandatory", "do_not_translate")
        ],
    )
    return EDITOR_SYSTEM, user


def _kept_terms(ctx: SegmentContext, before: str, after: str) -> list[str]:
    """Mandatory/DNT term forms present before the edit but missing after it."""
    lost = []
    for t in ctx.terms:
        form = (
            t.source_term
            if t.kind == "do_not_translate"
            else t.target_term
            if t.kind == "mandatory"
            else None
        )
        if form and form.casefold() in before.casefold() and form.casefold() not in after.casefold():
            lost.append(form)
    return lost


def apply_fixes(
    ctx: SegmentContext,
    confirmed_errors: list[MqmError],
    llm: LlmClient,
    *,
    tier: str = "ai_review",
    term_checker: Callable[[str], list[TermViolation]] | None = None,
) -> tuple[str, Usage]:
    """Return (new target tagged, usage). Returns the original target when there is nothing
    to fix, the model fails, or the edit would break a guarantee."""
    if tier != "ai_review":
        raise ValueError("the AI editor is only used on the ai_review tier")
    original = ctx.target_tagged
    if not confirmed_errors:
        return original, Usage()
    system, user = build_editor_prompt(ctx, confirmed_errors)
    try:
        data, usage, _model = llm.complete_json(system, user, schema_hint='{"target": "string"}')
    except EngineError as e:
        log.warning("editor failed for %s: %s", ctx.segment_id, e)
        return original, Usage()
    new = data.get("target")
    if not isinstance(new, str) or not new.strip():
        return original, usage
    if Counter(tags.token_list(new)) != Counter(tags.token_list(original)):
        log.info("editor rejected for %s: code tokens changed", ctx.segment_id)
        return original, usage
    if _kept_terms(ctx, tags.plain(original), tags.plain(new)):
        log.info("editor rejected for %s: glossary term lost", ctx.segment_id)
        return original, usage

    def blocking_codes(target: str) -> Counter[str]:
        violations = term_checker(target) if term_checker else None
        issues = run_hard_checks(replace(ctx, target_tagged=target), violations)
        return Counter(i.code for i in issues if i.blocking)

    if blocking_codes(new) - blocking_codes(original):
        log.info("editor rejected for %s: new blocking issue", ctx.segment_id)
        return original, usage
    return new, usage

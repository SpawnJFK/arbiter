"""A reviewer's decision on a held task: validation, pay, control grading, pipeline hooks.

Decisions: accept | edit | escalate | skip.
  * edit must keep the source's inline tags: any tag issue of severity "error" rejects the
    submission (D-009 policy, same as merge); dropping a whole formatting pair is allowed.
  * speed check: an accept faster than SPEED_MS_PER_WORD per word records a speed_flag score
    event and fraud_flags += 1. It never blocks; a human looks at repeated flags.
  * pay: see community.pay. Paid on `accepted`, through the ledger (task -> payable).
  * control task (hidden, known answer in task.expected): graded here; pass -> accepted and
    paid, fail -> rejected (not paid, can be disputed within 7 days). No pipeline hook: a
    control task is not real client work.
  * real task: accept/edit -> hooks.segment_reviewed, escalate -> hooks.segment_escalated,
    skip -> back to the queue for others, never offered to this reviewer again.
  * control sample (segment.is_control_sample: a blind check of an auto-approved segment)
    -> hooks.control_sample_verdict, escaped = an edit (or escalation) that reports a
    major/critical error. The segment is not moved to reviewed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from arbiter.billing import ledger
from arbiter.community import pay, scoring
from arbiter.community.errors import Conflict, Invalid, NotFound
from arbiter.community.queue import segment_words
from arbiter.community.transitions import move
from arbiter.fileproc.base import InlineCode, TaggedParseError, _split_tokens, from_tagged, validate_tags
from arbiter.models import ReviewerPair, ReviewerProfile, ReviewTask, Segment, utcnow
from arbiter.pipeline import hooks

DECISIONS = ("accept", "edit", "escalate", "skip")
SEVERITIES = ("neutral", "minor", "major", "critical")
SERIOUS = ("major", "critical")
SPEED_MS_PER_WORD = 600  # ~0.6 s per word: nobody reads and checks a segment faster


def source_content(segment: Segment) -> list[str | InlineCode]:
    """Rebuild the source Content from tagged text and the stored codes (ids/kinds from the text
    when source_codes is empty)."""
    codes: list[InlineCode] = []
    for c in segment.source_codes or []:
        if isinstance(c, dict) and "id" in c and "kind" in c:
            codes.append(
                InlineCode(
                    id=str(c["id"]),
                    kind=c["kind"],
                    original=c.get("original", ""),
                    display=c.get("display", ""),
                )
            )
    if not codes:
        for kind, value in _split_tokens(segment.source_tagged):
            if kind == "code" and isinstance(value, tuple):
                codes.append(InlineCode(id=value[0], kind=value[1]))  # type: ignore[arg-type]
    return from_tagged(segment.source_tagged, codes)


def check_tags(segment: Segment, target_tagged: str) -> list[dict[str, str]]:
    """Blocking tag issues of an edited target (empty list = ok)."""
    try:
        source = source_content(segment)
    except TaggedParseError as e:  # corrupt source is a pipeline bug, never the reviewer's
        raise Invalid(f"segment source cannot be parsed: {e}") from None
    return [
        {"kind": i.kind, "code_id": i.code_id, "detail": i.detail}
        for i in validate_tags(source, target_tagged)
        if i.severity == "error"
    ]


def _clean_errors(errors: Any) -> list[dict[str, Any]]:
    if errors is None:
        return []
    if not isinstance(errors, list):
        raise Invalid("errors must be a list")
    out = []
    for e in errors:
        if not isinstance(e, dict):
            raise Invalid("every error must be an object")
        sev = e.get("severity", "minor")
        if sev not in SEVERITIES:
            raise Invalid(f"error severity must be one of {', '.join(SEVERITIES)}")
        out.append(
            {
                "dimension": str(e.get("dimension") or e.get("category") or "other"),
                "severity": sev,
                "span": str(e.get("span") or ""),
                "explanation": str(e.get("explanation") or ""),
            }
        )
    return out


def _spans_overlap(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return bool(a and b and (a in b or b in a))


def grade_control(expected: dict[str, Any], decision: str, errors: list[dict[str, Any]]) -> bool:
    """Did the reviewer give the known answer?

    expected = {"decision": "accept"|"edit", "errors": [{"span", "severity", ...}]}
      * no serious expected error (clean or only minor): pass when the reviewer accepts or
        edits without reporting a major/critical error (minor polish is a matter of taste)
      * a serious expected error: pass when the reviewer edits or escalates and reports a
        major/critical error; if the expected errors carry spans, one must overlap
    """
    exp_errors = [e for e in (expected.get("errors") or []) if isinstance(e, dict)]
    serious_exp = [e for e in exp_errors if e.get("severity") in SERIOUS]
    if not serious_exp:
        return decision in ("accept", "edit") and not any(e["severity"] in SERIOUS for e in errors)
    if decision not in ("edit", "escalate"):
        return False
    serious_got = [e for e in errors if e["severity"] in SERIOUS]
    if not serious_got:
        return False
    spans = [e.get("span", "") for e in serious_exp if e.get("span")]
    if not spans:
        return True
    return any(_spans_overlap(s, g["span"]) for s in spans for g in serious_got)


def _pair(session: Session, profile: ReviewerProfile, task: ReviewTask) -> ReviewerPair | None:
    return scoring.pair_for_task(session, profile.id, task)


def submit(
    session: Session,
    profile: ReviewerProfile,
    task_id: str,
    *,
    decision: str,
    target_tagged: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    comment: str = "",
    time_ms: int = 0,
) -> dict[str, Any]:
    """POST /reviewer/tasks/{id}/submit -> {ok, pay_amount, state}."""
    if decision not in DECISIONS:
        raise Invalid(f"decision must be one of {', '.join(DECISIONS)}")
    task = session.get(ReviewTask, task_id, with_for_update=True)
    if task is None or task.reviewer_id != profile.id:
        raise NotFound("task not found")
    if task.state != "held":
        raise Conflict(f"task is {task.state}, not held by you")
    segment = session.get(Segment, task.segment_id)
    if segment is None:
        raise NotFound("segment not found")
    clean = _clean_errors(errors)
    time_ms = max(0, int(time_ms or 0))

    if decision == "skip":
        exp = dict(task.expected or {})
        exp["skipped_by"] = sorted({*exp.get("skipped_by", []), profile.id})
        task.expected = exp
        move(task, "task", "queued")
        task.reviewer_id = None
        task.hold_expires_at = None
        session.flush()
        return {"ok": True, "pay_amount": "0.00", "state": task.state}

    before = task.target_before if task.target_before is not None else (segment.target_tagged or "")
    if decision == "edit":
        if not isinstance(target_tagged, str) or not target_tagged.strip():
            raise Invalid("an edit needs target_tagged")
        issues = check_tags(segment, target_tagged)
        if issues:
            raise Invalid("the edited target breaks inline tags", {"tag_issues": issues})
        after = target_tagged
    else:
        after = before

    words = segment_words(segment)
    if decision == "accept" and time_ms < words * SPEED_MS_PER_WORD:
        profile.fraud_flags += 1
        scoring.record_event(
            session, profile, "speed_flag", task=task, note=f"accept in {time_ms} ms for {words} words"
        )

    task.decision = decision
    task.target_after = after
    task.errors = clean
    task.comment = (comment or "")[:5000]
    task.time_ms = time_ms
    task.submitted_at = utcnow()
    task.pay_amount = pay.task_pay(decision, words, profile.level)
    move(task, "task", "submitted")
    profile.decisions_total += 1

    if task.is_control:
        passed = grade_control(task.expected or {}, decision, clean)
        pair = _pair(session, profile, task)
        if pair is not None:
            pair.control_seen += 1
            pair.control_passed += 1 if passed else 0
        scoring.record_event(session, profile, "control_pass" if passed else "control_fail", task=task)
        if passed:
            move(task, "task", "accepted")
            pay.credit_task(session, task)
        else:
            move(task, "task", "rejected")  # pay_amount kept: paid if a dispute overturns it
        session.flush()
        paid = task.pay_amount if task.state == "payable" else 0
        return {"ok": True, "pay_amount": ledger.money(paid), "state": task.state}

    move(task, "task", "accepted")
    if decision in pay.PAID_DECISIONS:
        pay.credit_task(session, task)
    session.flush()

    serious = any(e["severity"] in SERIOUS for e in clean)
    if segment.is_control_sample:
        escaped = decision in ("edit", "escalate") and serious
        note = f"{decision}; {len(clean)} error(s) reported" + (
            "; escalated" if decision == "escalate" else ""
        )
        hooks.control_sample_verdict(session, segment.id, reviewer_id=profile.id, escaped=escaped, note=note)
    elif decision in ("accept", "edit"):
        hooks.segment_reviewed(
            session, segment.id, target_tagged=after, reviewer_id=profile.id, decision=decision, errors=clean
        )
    else:
        hooks.segment_escalated(
            session, segment.id, reviewer_id=profile.id, reason=task.comment or "escalated"
        )
    session.flush()
    return {"ok": True, "pay_amount": ledger.money(task.pay_amount), "state": task.state}

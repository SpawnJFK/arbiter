"""Quality estimation entry point and the routing decision.

``decide()`` turns a score into one of: auto_approve | senate | review | blocked.

Definitions:
    eff   = threshold + safety_offset   (safety_offset > 0 after a void senate or drift)
    HIGH  : score >= eff + band
    BAND  : eff - band < score < eff + band
    LOW   : score <= eff - band
For hybrid the band is split at eff: BAND_HI = eff <= score < eff + band, BAND_LO = below.

Decision table (a blocking hard issue -> "blocked" first, for every tier):

    tier       regulated  suspended | HIGH          BAND                   LOW
    ---------- ---------  --------- | ------------  ---------------------  --------
    auto       no         no        | auto_approve  senate                 review
    auto       no         yes       | senate        senate                 review
    ai_review  no         no        | auto_approve  senate                 senate
    ai_review  no         yes       | senate        senate                 senate
    hybrid     no         no        | auto_approve  HI: senate, LO: review review
    hybrid     no         yes       | review        review                 review
    full       any        any       | review        review                 review
    any        yes        any       | review        review                 review

Why:
* Regulated verticals never ship without a human (R-SEG-12): always review. Quote and
  project creation already forbid auto/ai_review for them; decide() enforces it again.
* full = the client paid for human review of every segment: always review. The score is
  still computed upstream for the reviewer UI and calibration.
* hybrid = human review except where the AI is confident: only HIGH auto-approves; the
  upper half of the band goes to the senate (a clean senate may auto-approve, which the
  pipeline decides), anything below the threshold goes to a human.
* ai_review = no human in the loop by contract, so where auto would send to a human the
  senate (+ editor) does the review instead.
* suspended (drift alarm or escaped errors on this threshold) = the score is not trusted
  for auto-approval: never auto_approve; auto/ai_review downgrade to an independent
  senate check, hybrid falls back to its human.
"""

from __future__ import annotations

from typing import Literal

from arbiter.contracts import Decision, LlmClient, QaIssue, QeResult, SegmentContext, TermViolation
from arbiter.quality.judge import judge

Tier = Literal["auto", "ai_review", "hybrid", "full"]
TIERS: tuple[str, ...] = ("auto", "ai_review", "hybrid", "full")


def score_segment(
    ctx: SegmentContext, llm: LlmClient, term_violations: list[TermViolation] | None = None
) -> QeResult:
    """Hard checks + LLM judge. Blocking hard issues give score 0 without a model call."""
    return judge(ctx, llm, term_violations)


def decide(
    score: float | None,
    hard_issues: list[QaIssue],
    threshold: float,
    band_width: float,
    *,
    tier: str,
    regulated: bool,
    safety_offset: float = 0.0,
    suspended: bool = False,
) -> Decision:
    """Route a scored segment. See the module docstring for the full table."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    if any(i.blocking for i in hard_issues):
        return "blocked"
    if regulated or tier == "full":
        return "review"
    if score is None:  # no score (judge failed): never guess
        return "senate" if tier == "ai_review" else "review"

    eff = threshold + max(0.0, safety_offset)
    high = score >= eff + band_width
    band = eff - band_width < score < eff + band_width

    if tier == "hybrid":
        if suspended:
            return "review"
        if high:
            return "auto_approve"
        if band and score >= eff:
            return "senate"
        return "review"

    if high:
        return "senate" if suspended else "auto_approve"
    if band:
        return "senate"
    return "senate" if tier == "ai_review" else "review"

"""Callbacks from the reviewer community into the pipeline.

The community module never changes segment or job state itself; it calls these.
Implemented in arbiter.pipeline.orchestrator; this module is the stable import point.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def segment_reviewed(
    session: Session,
    segment_id: str,
    *,
    target_tagged: str,
    reviewer_id: str,
    decision: str,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    """A human accepted or edited a segment. Moves it to `reviewed`, stores TM, maybe finishes the job."""
    from arbiter.pipeline.orchestrator import on_segment_reviewed

    on_segment_reviewed(
        session,
        segment_id,
        target_tagged=target_tagged,
        reviewer_id=reviewer_id,
        decision=decision,
        errors=errors or [],
    )


def segment_escalated(session: Session, segment_id: str, *, reviewer_id: str, reason: str) -> None:
    """A reviewer escalated (needs a senior / domain expert). Re-queued at a higher level."""
    from arbiter.pipeline.orchestrator import on_segment_escalated

    on_segment_escalated(session, segment_id, reviewer_id=reviewer_id, reason=reason)


def control_sample_verdict(
    session: Session, segment_id: str, *, reviewer_id: str, escaped: bool, note: str
) -> None:
    """A blind control review of an auto-approved segment finished (feeds calibration)."""
    from arbiter.pipeline.orchestrator import on_control_verdict

    on_control_verdict(session, segment_id, reviewer_id=reviewer_id, escaped=escaped, note=note)

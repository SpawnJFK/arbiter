"""Callbacks from the reviewer community into the pipeline.

The community module never changes segment or job state itself; it calls these.
Implemented in arbiter.pipeline.orchestrator; this module is the stable import point.

Adapters: a module that reuses the reviewer community for work that is not a pipeline job
(software strings) owns "carrier" jobs whose workflow snapshot names the adapter
({"adapter": "strings", ...}). Their review callbacks go to that module instead of the
orchestrator. The module is imported lazily, so removing it never breaks this import.
"""

from __future__ import annotations

import importlib
from typing import Any

from sqlalchemy.orm import Session

ADAPTERS: dict[str, str] = {"strings": "arbiter.strings.review"}


def _adapter(session: Session, segment_id: str) -> Any | None:
    from arbiter.models import Job, Segment

    seg = session.get(Segment, segment_id)
    job = session.get(Job, seg.job_id) if seg is not None else None
    name = (job.workflow or {}).get("adapter") if job is not None else None
    return importlib.import_module(ADAPTERS[name]) if name in ADAPTERS else None


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
    adapter = _adapter(session, segment_id)
    if adapter is not None:
        adapter.on_segment_reviewed(
            session,
            segment_id,
            target_tagged=target_tagged,
            reviewer_id=reviewer_id,
            decision=decision,
            errors=errors or [],
        )
        return
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

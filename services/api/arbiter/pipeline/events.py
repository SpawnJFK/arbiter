"""Provenance writer. Every segment change goes through record() (append-only table)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from arbiter.models import Job, ProvenanceEvent, Segment


def record(
    session: Session,
    job: Job,
    event: str,
    *,
    segment: Segment | None = None,
    actor_type: str = "system",
    actor_id: str = "",
    model_version: str = "",
    **data: Any,
) -> None:
    session.add(
        ProvenanceEvent(
            segment_id=segment.id if segment is not None else None,
            job_id=job.id,
            org_id=job.org_id,
            event=event,
            actor_type=actor_type,
            actor_id=actor_id,
            model_version=model_version,
            data=_jsonable(data),
        )
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

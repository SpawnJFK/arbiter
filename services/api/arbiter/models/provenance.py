"""Provenance: the append-only history of every segment.

Every change to a segment (engine output, QE score, senate verdict, human edit,
approval, delivery) writes one event. The table is append-only: a database trigger
(created in the initial migration) rejects UPDATE and DELETE, so the evidence pack
we hand to a client can never be rewritten after the fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column

APPEND_ONLY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION provenance_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'provenance_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS provenance_no_update ON provenance_events;
CREATE TRIGGER provenance_no_update
    BEFORE UPDATE OR DELETE ON provenance_events
    FOR EACH ROW EXECUTE FUNCTION provenance_append_only();
"""


class ProvenanceEvent(Base):
    __tablename__ = "provenance_events"
    __table_args__ = (Index("ix_prov_segment", "segment_id", "at"), Index("ix_prov_job", "job_id", "at"))

    id: Mapped[str] = id_column("prv")
    # No FK on purpose: provenance outlives deleted segments (retention deletes content, not history).
    segment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    job_id: Mapped[str] = mapped_column(String(40))
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    # e.g. tm_hit | mt_output | qe_scored | senate | edited | approved | reviewed | delivered | reopened
    event: Mapped[str] = mapped_column(String(40))
    actor_type: Mapped[str] = mapped_column(String(10))  # engine | human | system
    actor_id: Mapped[str] = mapped_column(String(120), default="")
    model_version: Mapped[str] = mapped_column(String(120), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = created_at_column()

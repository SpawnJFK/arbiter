"""Workbench (module tms) and auditor (module auditor) tables, migration 0008.

segment_comments  comments and client queries per segment, threaded
tm_alignments     a source + translated document pair aligned into a review grid before TM import
audits            one standalone QA/LQA run over a bilingual file from any tool
audit_segments    the segments of an audit with their issues
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class SegmentComment(Base):
    """A comment (internal, PM and team) or a query to the client about one segment.

    thread_id is the id of the root comment (a root points at itself). Queries are the
    only kind a client user sees; the client answers by replying in the thread.
    """

    __tablename__ = "segment_comments"
    __table_args__ = (
        Index("ix_comments_job_segment", "job_id", "segment_id"),
        Index("ix_comments_thread", "thread_id"),
    )

    id: Mapped[str] = id_column("cmt")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    # No FK: a comment outlives a segment merged away (its history is still useful).
    segment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    thread_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10), default="comment")  # comment | query
    author_id: Mapped[str] = mapped_column(String(40), default="")
    author_role: Mapped[str] = mapped_column(String(20), default="")
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class TmAlignment(Base):
    """Review grid of an aligned document pair. pairs: [{index, source, target, confidence,
    src: [sentence idx], tgt: [sentence idx], accepted}]."""

    __tablename__ = "tm_alignments"

    id: Mapped[str] = id_column("aln")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    source_filename: Mapped[str] = mapped_column(String(400))
    target_filename: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    pairs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="review")  # review | committed
    committed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = created_at_column()
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Audit(Base):
    """A standalone QA/LQA audit. State machine "audit" in domain/states.py."""

    __tablename__ = "audits"

    id: Mapped[str] = id_column("aud")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    input_format: Mapped[str] = mapped_column(String(20))  # xliff | tmx | csv | xlsx | pair
    filename: Mapped[str] = mapped_column(String(400))
    storage_key: Mapped[str] = mapped_column(String(400))
    target_filename: Mapped[str | None] = mapped_column(String(400), nullable=True)
    target_storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    glossary_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # {ai_mode: none|sample|full, ai_sample_pct, threshold, consistency, content_type}
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    segments_total: Mapped[int] = mapped_column(Integer, default=0)
    segments_done: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mqm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)  # pass | fail
    ai_units: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditSegment(Base):
    __tablename__ = "audit_segments"
    __table_args__ = (Index("ix_audit_segments_seq", "audit_id", "seq"),)

    id: Mapped[str] = id_column("aus")
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    unit_id: Mapped[str] = mapped_column(String(200), default="")
    source_tagged: Mapped[str] = mapped_column(Text)
    target_tagged: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # [{code, severity, message, blocking, kind: qa|term|consistency, dimension, mqm_severity}]
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mqm_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Highest MQM severity on the segment (none | neutral | minor | major | critical), for filters.
    max_severity: Mapped[str] = mapped_column(String(10), default="none")
    dimensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    checked: Mapped[bool] = mapped_column(Boolean, default=False)

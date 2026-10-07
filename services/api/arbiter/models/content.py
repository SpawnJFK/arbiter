"""Projects, files, jobs and segments.

A Project groups the jobs of one order. A Job is one file in one language pair.
A Segment is the smallest unit that is translated, scored and routed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = id_column("prj")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_langs: Mapped[list[str]] = mapped_column(JSON)
    tier: Mapped[str] = mapped_column(String(20))  # auto | ai_review | hybrid | full
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class FileAsset(Base):
    __tablename__ = "files"

    id: Mapped[str] = id_column("fil")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    filename: Mapped[str] = mapped_column(String(400))
    format: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(400))
    source_lang: Mapped[str] = mapped_column(String(16))
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = id_column("job")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    tier: Mapped[str] = mapped_column(String(20))
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    state: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # Versions frozen at job start (R-GL-11): later glossary edits never change a running job.
    glossary_version: Mapped[int] = mapped_column(Integer, default=0)
    threshold: Mapped[float] = mapped_column(Float, default=78.0)
    band_width: Mapped[float] = mapped_column(Float, default=8.0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    weighted_words: Mapped[float] = mapped_column(Float, default=0.0)
    est_auto_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_approved_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_reviewed_count: Mapped[int] = mapped_column(Integer, default=0)
    # Money per job, so PM sees margin per job, not per month.
    cost_engines: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    cost_reviewers: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    revenue: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    no_reviewer_fallback_used: Mapped[bool] = mapped_column(default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    evidence_storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        Index("ix_segments_job_seq", "job_id", "seq"),
        Index("ix_segments_job_state", "job_id", "state"),
    )

    id: Mapped[str] = id_column("seg")
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # order within the job
    unit_id: Mapped[str] = mapped_column(String(200))
    seg_index: Mapped[int] = mapped_column(Integer)  # order within the unit
    context: Mapped[str] = mapped_column(String(200), default="")
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_tagged: Mapped[str] = mapped_column(Text)
    source_plain: Mapped[str] = mapped_column(Text)
    source_codes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    target_tagged: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    origin: Mapped[str | None] = mapped_column(String(20), nullable=True)  # tm | mt | editor | human
    engine: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tm_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    tm_entry_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qe_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    engine_target_tagged: Mapped[str | None] = mapped_column(Text, nullable=True)  # what the engine produced
    edit_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_control_sample: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = created_at_column()

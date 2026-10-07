"""Quality: thresholds, senate runs, engine scoreboard, control samples, escaped errors."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow


class Threshold(Base):
    """Auto-approval threshold per organization, content type and target language.

    Phrase scopes its QPS threshold to global/template/project/job only. Per target
    language is ours because Serbian or Finnish cannot share Spanish's threshold.
    target_lang NULL = default for all languages of that content type.
    """

    __tablename__ = "thresholds"
    __table_args__ = (UniqueConstraint("org_id", "content_type", "target_lang"),)

    id: Mapped[str] = id_column("thr")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    target_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    value: Mapped[float] = mapped_column(Float, default=78.0)
    band_width: Mapped[float] = mapped_column(Float, default=8.0)
    # Raised temporarily when a senate role is down or drift is detected; cleared by calibration.
    safety_offset: Mapped[float] = mapped_column(Float, default=0.0)
    auto_approval_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_calibrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SenateRun(Base):
    """One convening of the council over one segment.

    findings holds every role's raw findings separately. A client paying for the senate
    must be able to see who said what, otherwise they pay for a black box.
    """

    __tablename__ = "senate_runs"

    id: Mapped[str] = id_column("sen")
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # review | translation | triage
    roles_answered: Mapped[int] = mapped_column(Integer, default=0)
    roles_total: Mapped[int] = mapped_column(Integer, default=4)
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # role -> list[finding]
    confirmed: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    discarded: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))  # clean | errors_confirmed | void | winner:<engine>
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    created_at: Mapped[datetime] = created_at_column()


class EngineScore(Base):
    """The scoreboard: which engine wins for which pair and domain, measured on our own jobs."""

    __tablename__ = "engine_scores"
    __table_args__ = (UniqueConstraint("engine", "source_lang", "target_lang", "domain"),)

    id: Mapped[str] = id_column("eng")
    engine: Mapped[str] = mapped_column(String(80))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(60), default="general")
    segments_measured: Mapped[int] = mapped_column(Integer, default=0)
    mean_edit_distance: Mapped[float] = mapped_column(Float, default=0.0)
    mean_qe: Mapped[float] = mapped_column(Float, default=0.0)
    mandatory_terms_seen: Mapped[int] = mapped_column(Integer, default=0)
    mandatory_terms_kept: Mapped[int] = mapped_column(Integer, default=0)
    glossary_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def term_adherence(self) -> float | None:
        if not self.mandatory_terms_seen:
            return None
        return self.mandatory_terms_kept / self.mandatory_terms_seen


class ControlSample(Base):
    """A blind check: an auto-approved segment sent to a reviewer who does not know it was approved."""

    __tablename__ = "control_samples"

    id: Mapped[str] = id_column("ctl")
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    qe_score: Mapped[float] = mapped_column(Float)
    reviewer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok | escaped
    created_at: Mapped[datetime] = created_at_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EscapedError(Base):
    """An error in a segment that shipped. Feeds calibration (spec: escaped_error)."""

    __tablename__ = "escaped_errors"
    __table_args__ = (Index("ix_escaped_org_ct", "org_id", "content_type", "target_lang"),)

    id: Mapped[str] = id_column("esc")
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(String(40))
    org_id: Mapped[str] = mapped_column(String(40))
    content_type: Mapped[str] = mapped_column(String(60))
    target_lang: Mapped[str] = mapped_column(String(16))
    qe_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_auto_approved: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(16))  # control | client
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = created_at_column()


class QualityMetric(Base):
    """Daily per-role, per-pair counters used for drift detection (scenario B in the rulebook)."""

    __tablename__ = "quality_metrics"
    __table_args__ = (UniqueConstraint("day", "metric", "engine", "source_lang", "target_lang"),)

    id: Mapped[str] = id_column("qm")
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    metric: Mapped[str] = mapped_column(String(60))  # e.g. "flags_per_segment:accuracy"
    engine: Mapped[str] = mapped_column(String(80), default="")
    source_lang: Mapped[str] = mapped_column(String(16), default="")
    target_lang: Mapped[str] = mapped_column(String(16), default="")
    total: Mapped[float] = mapped_column(Float, default=0.0)
    count: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str] = mapped_column(String(120), default="")

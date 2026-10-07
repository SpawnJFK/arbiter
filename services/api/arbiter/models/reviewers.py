"""The reviewer community: profiles, language pairs, tests, tasks, score, disputes.

A reviewer applies, passes a language test and a practical test per pair, and is then
offered review tasks. A hidden share of tasks are control tasks with a known answer;
they feed the reviewer score. Pay is per decision and per word, accrued in the ledger.
"""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class ReviewerProfile(Base):
    __tablename__ = "reviewer_profiles"

    id: Mapped[str] = id_column("rvw")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    level: Mapped[str] = mapped_column(
        String(20), default="candidate"
    )  # candidate | reviewer | senior | domain_expert
    status: Mapped[str] = mapped_column(
        String(20), default="applied"
    )  # applied | active | suspended | banned
    domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    country: Mapped[str] = mapped_column(String(2), default="")
    # Platform-operator reporting (EU DAC7 and equivalents) needs these before the first payout.
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    tax_id: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    date_of_birth: Mapped[str] = mapped_column(String(10), default="")
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    payout_method: Mapped[str] = mapped_column(String(20), default="")  # wise | paypal | sepa
    payout_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payout_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("50"))
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100, see reviewers.scoring
    decisions_total: Mapped[int] = mapped_column(Integer, default=0)
    fraud_flags: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at_column()


class ReviewerPair(Base):
    __tablename__ = "reviewer_pairs"
    __table_args__ = (UniqueConstraint("reviewer_id", "source_lang", "target_lang"),)

    id: Mapped[str] = id_column("rvp")
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), index=True
    )
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="locked")  # locked | testing | active | demoted
    score: Mapped[float] = mapped_column(Float, default=0.0)
    control_seen: Mapped[int] = mapped_column(Integer, default=0)
    control_passed: Mapped[int] = mapped_column(Integer, default=0)
    retest_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class ReviewerTest(Base):
    __tablename__ = "reviewer_tests"

    id: Mapped[str] = id_column("tst")
    kind: Mapped[str] = mapped_column(String(20))  # language | practical
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(60), default="general")
    # Practical items: {"source", "target", "errors": [{"span", "category", "severity"}]}.
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    pass_mark: Mapped[float] = mapped_column(Float, default=80.0)
    time_limit_min: Mapped[int] = mapped_column(Integer, default=45)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()


class TestAttempt(Base):
    __tablename__ = "test_attempts"
    __test__ = False  # not a pytest class

    id: Mapped[str] = id_column("att")
    test_id: Mapped[str] = mapped_column(ForeignKey("reviewer_tests.id"))
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), index=True
    )
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("ix_tasks_queue", "state", "source_lang", "target_lang", "priority"),
        Index("ix_tasks_reviewer", "reviewer_id", "state"),
    )

    id: Mapped[str] = id_column("tsk")
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(60), default="general")
    min_level: Mapped[str] = mapped_column(String(20), default="reviewer")
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = sooner (deadline driven)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    reviewer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Hidden control task: reviewer never knows; expected holds the known answer.
    is_control: Mapped[bool] = mapped_column(Boolean, default=False)
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # accept | edit | escalate | skip
    target_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    comment: Mapped[str] = mapped_column(Text, default="")
    time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_amount: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=Decimal("0"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewerScoreEvent(Base):
    __tablename__ = "reviewer_score_events"

    id: Mapped[str] = id_column("rse")
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(30)
    )  # control_pass | control_fail | escaped | dispute_won | dispute_lost | speed_flag
    delta: Mapped[float] = mapped_column(Float)
    score_after: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = created_at_column()


class Dispute(Base):
    """A reviewer contests a rejection. Decided by a senior within 48 hours."""

    __tablename__ = "disputes"

    id: Mapped[str] = id_column("dsp")
    task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id", ondelete="CASCADE"), unique=True)
    reviewer_id: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | upheld | overturned | expired
    decided_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

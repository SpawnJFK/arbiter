"""Linguistic assets: translation memory, glossaries, style cards, open term questions.

Glossary versioning is temporal: every change bumps the glossary version and a term
is valid for [valid_from, valid_to). A job freezes the version it started with, so a
glossary edited mid-job never changes that job (R-GL-11) and we can always answer
"why was this different last month".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow

EMBED_DIM = 256


class TmEntry(Base):
    __tablename__ = "tm_entries"
    __table_args__ = (
        Index("ix_tm_lookup", "org_id", "source_lang", "target_lang", "source_hash"),
        Index(
            "ix_tm_trgm",
            "source_plain",
            postgresql_using="gin",
            postgresql_ops={"source_plain": "gin_trgm_ops"},
        ),
    )

    id: Mapped[str] = id_column("tmu")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    source_tagged: Mapped[str] = mapped_column(Text)
    target_tagged: Mapped[str] = mapped_column(Text)
    source_plain: Mapped[str] = mapped_column(Text)
    target_plain: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    # Context hash = hash of previous + next source segment: an exact match with the same
    # context is a "101%" / in-context match and may skip the engine entirely (R-TM-03).
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="approved")  # approved | stale | imported
    origin: Mapped[str] = mapped_column(String(20), default="review")  # review | import | client
    rights_confirmed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)  # R-TM-01
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Glossary(Base):
    __tablename__ = "glossaries"

    id: Mapped[str] = id_column("gls")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Glossaries bind to a content type, not to the client: one client can have one
    # glossary per product line. NULL = applies to all content types.
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = created_at_column()


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (Index("ix_terms_lookup", "glossary_id", "source_lang", "target_lang"),)

    id: Mapped[str] = id_column("trm")
    glossary_id: Mapped[str] = mapped_column(ForeignKey("glossaries.id", ondelete="CASCADE"))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    source_term: Mapped[str] = mapped_column(String(500))
    # NULL for do_not_translate (target = source) and for forbidden (target term is the forbidden string).
    target_term: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # mandatory | preferred | forbidden | do_not_translate
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    valid_from: Mapped[int] = mapped_column(Integer, default=1)
    valid_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class StyleCard(Base):
    """Summary of a client's approved corrections, injected into prompts."""

    __tablename__ = "style_cards"

    id: Mapped[str] = id_column("sty")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    target_lang: Mapped[str] = mapped_column(String(16))
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    rules: Mapped[list[str]] = mapped_column(JSON, default=list)  # short imperative rules
    formality: Mapped[str | None] = mapped_column(String(20), nullable=True)  # formal | informal
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TermQuestion(Base):
    """A term with no approved target for this language (R-TM-06) or a reviewer proposal."""

    __tablename__ = "term_questions"

    id: Mapped[str] = id_column("tq")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    segment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    source_term: Mapped[str] = mapped_column(String(500))
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | answered | dismissed
    answer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

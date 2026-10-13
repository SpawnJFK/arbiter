"""Operational tables: direct upload sessions, outgoing email log, single-use account tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class UploadSession(Base):
    """One direct upload: the client PUTs the bytes to storage, then calls complete."""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = id_column("upl")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(60))  # user id or API key id
    filename: Mapped[str] = mapped_column(String(400))
    size: Mapped[int] = mapped_column(BigInteger)  # declared by the client, checked on complete
    content_type: Mapped[str] = mapped_column(String(200))
    source_lang: Mapped[str] = mapped_column(String(16))
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # handler options (0011)
    storage_key: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | completed | rejected
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailMessage(Base):
    """Every email the platform sends, queued in the same transaction as its cause.

    `context` holds the template variables until the message is sent; for real backends it
    is cleared after sending so single-use links do not linger in the database.
    """

    __tablename__ = "email_messages"
    __table_args__ = (Index("ix_email_messages_to", "to_address", "created_at"),)

    id: Mapped[str] = id_column("eml")
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    to_address: Mapped[str] = mapped_column(String(320))
    template: Mapped[str] = mapped_column(String(60))
    subject: Mapped[str] = mapped_column(String(300), default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # kept by the log backend only
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | sent | logged | failed
    backend: Mapped[str] = mapped_column(String(16), default="")
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccountToken(Base):
    """Single-use, expiring token for password reset and invitations. Only the hash is stored."""

    __tablename__ = "account_tokens"

    id: Mapped[str] = id_column("atk")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # reset | invite
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

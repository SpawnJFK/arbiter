"""UI string localization store (platform-wide, managed by the platform admin).

English is the source: the EN catalog lives in the web repo. Translations of it are stored
here per locale and can be imported or edited without a redeploy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, utcnow


class UiLocale(Base):
    __tablename__ = "ui_locales"

    locale: Mapped[str] = mapped_column(String(35), primary_key=True)  # BCP-47, normalised
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()


class UiMessage(Base):
    __tablename__ = "ui_messages"
    __table_args__ = (UniqueConstraint("locale", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    locale: Mapped[str] = mapped_column(ForeignKey("ui_locales.locale", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

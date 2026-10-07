"""Shared column helpers.

Ids are prefixed, time-sortable strings ("job_01JA3...") so they read well in logs,
URLs and support tickets, sort by creation time, and never collide across tables.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """ULID-style: 48-bit ms timestamp + 80 random bits, Crockford base32."""
    ts = int(time.time() * 1000)
    rnd = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_b32(ts, 10)}{_b32(rnd, 16)}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def id_column(prefix: str) -> Mapped[str]:
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

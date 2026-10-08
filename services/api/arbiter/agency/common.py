"""Small helpers shared by the agency services."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from arbiter.errors import Invalid

TIERS = ("auto", "ai_review", "hybrid", "full")
HUMANLESS_TIERS = ("auto", "ai_review")
REGULATED_REASON = "Regulated vertical: every segment needs a human reviewer (R-SEG-12)."


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def money(value: Decimal | int | str | None) -> str:
    """Decimal -> contract money string ("12.40")."""
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def decimal(
    value: Any, what: str, *, places: str | None = None, minimum: Decimal | None = Decimal("0")
) -> Decimal:
    """Parse a decimal from a string or int (never trusts floats beyond their str form)."""
    if isinstance(value, bool):
        raise Invalid(f"{what} must be a decimal number")
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise Invalid(f"{what} must be a decimal number, got {value!r}") from None
    if not d.is_finite():
        raise Invalid(f"{what} must be a finite number")
    if minimum is not None and d < minimum:
        raise Invalid(f"{what} must be >= {minimum}")
    return d.quantize(Decimal(places)) if places else d


def currency(value: str | None, default: str = "EUR") -> str:
    cur = (value or default).strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise Invalid("currency must be a 3-letter ISO code, e.g. EUR")
    return cur


def lang(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower().replace("_", "-")
    return v or None


_LOCALE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{4}))?(?:[-_]([A-Za-z]{2}|\d{3}))?$")


def normalize_locale(value: str | None, default: str = "en") -> str:
    """BCP-47 language[-Script][-REGION], normalised: "sr-latn-rs" -> "sr-Latn-RS"."""
    if value is None or not value.strip():
        return default
    m = _LOCALE.match(value.strip())
    if not m:
        raise Invalid(f"locale must be a BCP-47 tag like en, de, pt-BR or sr-Latn, got {value!r}")
    lang_, script, region = m.groups()
    out = lang_.lower()
    if script:
        out += "-" + script.title()
    if region:
        out += "-" + region.upper()
    return out

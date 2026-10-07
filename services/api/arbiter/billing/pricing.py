"""Client price list: per-word rate per tier and TM leverage discounts.

STARTING VALUES, not market-validated. They exist so quotes work end to end; the owner sets
real prices before launch. Override per organization in org.settings:

    {"pricing": {"tiers": {"hybrid": "0.06"}, "tm_weights": {"fuzzy_75_84": "0.7"}, "minimum": "5"}}

Weighted words = sum over bands of words * band weight. Bands follow the usual CAT-tool
analysis (R-TM-03 match ladder; semantic matches are never leverage, R-TM-04):

    band           match                       weight
    context        101 (same source+context)   0.1
    exact          100                         0.1
    fuzzy_95_99    fuzzy 95-99                 0.3
    fuzzy_85_94    fuzzy 85-94                 0.6
    fuzzy_75_84    fuzzy 75-84                 0.8
    new            no match / < 75             1.0
    repetitions    repeated within the file    0.1
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from arbiter.models import Organization

TIERS = ("auto", "ai_review", "hybrid", "full")
TIER_RATES: dict[str, Decimal] = {  # EUR per weighted word
    "auto": Decimal("0.02"),
    "ai_review": Decimal("0.04"),
    "hybrid": Decimal("0.07"),
    "full": Decimal("0.12"),
}
BANDS = ("context", "exact", "fuzzy_95_99", "fuzzy_85_94", "fuzzy_75_84", "new", "repetitions")
TM_WEIGHTS: dict[str, Decimal] = {
    "context": Decimal("0.1"),
    "exact": Decimal("0.1"),
    "fuzzy_95_99": Decimal("0.3"),
    "fuzzy_85_94": Decimal("0.6"),
    "fuzzy_75_84": Decimal("0.8"),
    "new": Decimal("1.0"),
    "repetitions": Decimal("0.1"),
}
MINIMUM_CHARGE = Decimal("5.00")


def _dec(value: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid {what} in org pricing settings: {value!r}") from None
    if d < 0:
        raise ValueError(f"negative {what} in org pricing settings")
    return d


def _overrides(org: Organization | None) -> dict[str, Any]:
    if org is None:
        return {}
    p = (org.settings or {}).get("pricing") or {}
    return p if isinstance(p, dict) else {}


def tier_rates(org: Organization | None = None) -> dict[str, Decimal]:
    rates = dict(TIER_RATES)
    for tier, v in (_overrides(org).get("tiers") or {}).items():
        if tier in rates:
            rates[tier] = _dec(v, f"rate for {tier}")
    return rates


def tm_weights(org: Organization | None = None) -> dict[str, Decimal]:
    w = dict(TM_WEIGHTS)
    for band, v in (_overrides(org).get("tm_weights") or {}).items():
        if band in w:
            w[band] = _dec(v, f"weight for {band}")
    return w


def minimum_charge(org: Organization | None = None) -> Decimal:
    v = _overrides(org).get("minimum")
    return _dec(v, "minimum") if v is not None else MINIMUM_CHARGE


def band_for(kind: str | None, score: float | None) -> str:
    """TM match -> analysis band (R-TM-03). Semantic matches are not leverage (R-TM-04)."""
    if kind == "context":
        return "context"
    if kind == "exact":
        return "exact"
    if kind == "fuzzy" and score is not None:
        if score >= 95:
            return "fuzzy_95_99"
        if score >= 85:
            return "fuzzy_85_94"
        if score >= 75:
            return "fuzzy_75_84"
    return "new"


def weighted_words(bands: dict[str, int], weights: dict[str, Decimal] | None = None) -> Decimal:
    w = weights or TM_WEIGHTS
    return sum((Decimal(bands.get(b, 0)) * w[b] for b in BANDS), Decimal("0"))

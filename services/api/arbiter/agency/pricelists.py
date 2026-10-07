"""Price lists: per-word rates per language pair and tier, TM weights, minimum charge.

Rate lookup for (source_lang, target_lang, tier), most specific first:
  1. exact pair + tier       rate with source_lang and target_lang both matching
  2. target-only + tier      rate with target_lang matching and no source_lang
  3. tier-only               rate with neither language (a rate with only a source_lang
                             counts here too, when that source matches)
  4. org default             billing.pricing.tier_rates(org) (org.settings overrides)
Languages compare case-insensitively ("sr-Latn" == "sr-latn").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.agency.common import currency, iso, lang, money
from arbiter.agency.schemas import PriceListIn, PriceListPatch, RateIn
from arbiter.billing import pricing
from arbiter.errors import Invalid, NotFound
from arbiter.models import Organization, PriceList, utcnow

# Contract tm_weights keys -> billing.pricing analysis bands.
WEIGHT_BANDS: dict[str, str] = {
    "context": "context",
    "exact": "exact",
    "fuzzy_95": "fuzzy_95_99",
    "fuzzy_85": "fuzzy_85_94",
    "fuzzy_75": "fuzzy_75_84",
    "new": "new",
    "repetition": "repetitions",
}


def get_price_list(session: Session, org_id: str, pl_id: str, *, include_archived: bool = False) -> PriceList:
    pl = session.execute(
        select(PriceList).where(PriceList.id == pl_id, PriceList.org_id == org_id)
    ).scalar_one_or_none()
    if pl is None or (pl.archived_at is not None and not include_archived):
        raise NotFound("price list not found")
    return pl


def find_by_name(session: Session, org_id: str, name: str) -> PriceList | None:
    return (
        session.execute(
            select(PriceList).where(
                PriceList.org_id == org_id,
                func.lower(PriceList.name) == name.strip().lower(),
                PriceList.archived_at.is_(None),
            )
        )
        .scalars()
        .first()
    )


def _rates(rates: list[RateIn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for r in rates:
        key = (lang(r.source_lang), lang(r.target_lang), r.tier)
        if key in seen:
            raise Invalid(
                "duplicate rate for the same languages and tier",
                {"source_lang": key[0], "target_lang": key[1], "tier": key[2]},
            )
        seen.add(key)
        out.append(
            {
                "source_lang": key[0],
                "target_lang": key[1],
                "tier": r.tier,
                "per_word": str(r.per_word.normalize()),
            }
        )
    return out


def _weights(w: dict[str, Decimal] | None) -> dict[str, str] | None:
    if w is None:
        return None
    out = {}
    for k, v in w.items():
        if v < 0 or v > 2:
            raise Invalid(f"tm weight {k} must be between 0 and 2")
        out[k] = str(v)
    return out


def create_price_list(session: Session, org_id: str, body: PriceListIn) -> PriceList:
    pl = PriceList(
        org_id=org_id,
        name=body.name,
        currency=currency(body.currency),
        rates=_rates(body.rates),
        tm_weights=_weights(body.tm_weights),
        minimum_charge=body.minimum_charge,
    )
    session.add(pl)
    session.flush()
    return pl


def update_price_list(session: Session, pl: PriceList, body: PriceListPatch) -> PriceList:
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        if not data["name"]:
            raise Invalid("name cannot be empty")
        pl.name = data["name"]
    if "currency" in data:
        pl.currency = currency(data["currency"])
    if "rates" in data:
        if body.rates is None:
            raise Invalid("rates cannot be null")
        pl.rates = _rates(body.rates)
    if "tm_weights" in data:
        pl.tm_weights = _weights(body.tm_weights)
    if "minimum_charge" in data:
        pl.minimum_charge = body.minimum_charge
    pl.updated_at = utcnow()
    session.flush()
    return pl


def archive_price_list(session: Session, pl: PriceList) -> PriceList:
    """DELETE archives (accounts and past quotes may still point at it)."""
    pl.archived_at = pl.archived_at or utcnow()
    session.flush()
    return pl


def price_list_view(pl: PriceList) -> dict[str, Any]:
    return {
        "id": pl.id,
        "name": pl.name,
        "currency": pl.currency,
        "rates": [dict(r) for r in (pl.rates or [])],
        "tm_weights": dict(pl.tm_weights) if pl.tm_weights is not None else None,
        "minimum_charge": money(pl.minimum_charge) if pl.minimum_charge is not None else None,
        "archived": pl.archived_at is not None,
        "created_at": iso(pl.created_at),
        "updated_at": iso(pl.updated_at),
    }


# --------------------------------------------------------------------------- pricing hooks


def rate_for(
    pl: PriceList, source_lang: str, target_lang: str, tier: str, org: Organization | None = None
) -> tuple[Decimal, str]:
    """Per-word rate and which rule matched: pair | target | tier | org_default."""
    s, t = lang(source_lang), lang(target_lang)
    best: tuple[int, Decimal] | None = None
    for r in pl.rates or []:
        if r.get("tier") != tier:
            continue
        rs, rt = r.get("source_lang"), r.get("target_lang")
        if rt is not None and rt != t:
            continue
        if rs is not None and rs != s:
            continue
        rank = 0 if (rs and rt) else 1 if rt else 2
        if best is None or rank < best[0]:
            best = (rank, Decimal(str(r["per_word"])))
    if best is not None:
        return best[1], ("pair", "target", "tier")[best[0]]
    return pricing.tier_rates(org)[tier], "org_default"


def tm_weights_for(pl: PriceList, org: Organization | None = None) -> dict[str, Decimal]:
    weights = pricing.tm_weights(org)
    for k, v in (pl.tm_weights or {}).items():
        band = WEIGHT_BANDS.get(k)
        if band:
            weights[band] = Decimal(str(v))
    return weights


def minimum_for(pl: PriceList, org: Organization | None = None) -> Decimal:
    return pl.minimum_charge if pl.minimum_charge is not None else pricing.minimum_charge(org)

"""Quotes: file analysis against the TM, price per tier, availability.

Analysis (per target language):
  * every segment of the file is looked up in the org's TM (context/exact/fuzzy, no semantic
    matches: they are not leverage, R-TM-04); context hash = previous + next source segment
  * a segment whose exact source already appeared earlier in the file is a repetition, unless
    the TM gives it a context/exact match (the better band wins)
  * words per band -> weighted words (billing.pricing)

Price per tier = max(minimum, sum over target languages of weighted words * tier rate),
rounded to the cent.

est_auto_rate (share of segments expected to ship without a human):
  history = jobs of this org, same content_type and pair, created in the last 90 days, with
  segments: sum(auto_approved_count) / sum(segment_count). Without history a conservative prior
  of 0.5 is used. `full` is always 0 (a human sees every segment). Averaged over target langs,
  weighted by words.

eta_hours (rough, for the client's expectations, not a promise):
  machine  = 0.1 + words_total / 50_000
  auto     = machine
  ai_review= machine + (1 - auto_rate) * words_total / 20_000
  hybrid   = machine + (1 - auto_rate) * words_total / (REVIEW_WORDS_PER_HOUR * PARALLEL_REVIEWERS)
  full     = machine + words_total / (REVIEW_WORDS_PER_HOUR * PARALLEL_REVIEWERS)
  with REVIEW_WORDS_PER_HOUR = 500 and PARALLEL_REVIEWERS = 3.

Regulated organizations never get `auto` or `ai_review` (R-SEG-12): those tiers are returned
with available=false and a blocked_reason, and project creation must refuse them too.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.billing import pricing
from arbiter.billing.ledger import money
from arbiter.community.errors import Invalid
from arbiter.config import get_settings
from arbiter.fileproc import registry
from arbiter.fileproc.base import FormatError, plain_text, to_tagged
from arbiter.linguistic import tm
from arbiter.models import FileAsset, Job, Organization, Quote, utcnow

HISTORY_DAYS = 90
AUTO_RATE_PRIOR = 0.5
REVIEW_WORDS_PER_HOUR = 500
PARALLEL_REVIEWERS = 3
REGULATED_REASON = "Regulated vertical: every segment needs a human reviewer (R-SEG-12)."
_WORD = re.compile(r"\w+", re.U)
CENT = Decimal("0.01")


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def _norm(tagged: str) -> str:
    return " ".join(tagged.split())


def _segments(file_asset: FileAsset) -> list[tuple[str, int]]:
    try:
        data = storage.get(file_asset.storage_key)
    except (FileNotFoundError, ValueError):
        raise Invalid("the file is no longer available") from None
    try:
        result = registry.detect_and_extract(file_asset.filename, data, file_asset.source_lang)
    except FormatError as e:
        raise Invalid(str(e)) from None
    out: list[tuple[str, int]] = []
    for unit in result.units:
        for seg in unit.segments:
            tagged = to_tagged(seg.content)
            words = count_words(plain_text(seg.content))
            if tagged.strip():
                out.append((tagged, words))
    return out


def analyse(
    session: Session, org_id: str, source_lang: str, target_lang: str, segments: list[tuple[str, int]]
) -> dict[str, int]:
    """Words per band for one target language (see module docstring)."""
    bands = dict.fromkeys(pricing.BANDS, 0)
    seen: set[str] = set()
    cache: dict[tuple[str, str], tuple[str | None, float | None]] = {}
    for i, (tagged, words) in enumerate(segments):
        prev_s = segments[i - 1][0] if i > 0 else None
        next_s = segments[i + 1][0] if i + 1 < len(segments) else None
        chash = tm.context_hash(prev_s, next_s)
        key = (tagged, chash)
        if key not in cache:
            matches = tm.lookup(
                session, org_id, source_lang, target_lang, tagged, chash, limit=1, use_semantic=False
            )
            cache[key] = (matches[0].kind, matches[0].score) if matches else (None, None)
        kind, score = cache[key]
        band = pricing.band_for(kind, score)
        norm = _norm(tagged)
        if band not in ("context", "exact") and norm in seen:
            band = "repetitions"
        seen.add(norm)
        bands[band] += words
    return bands


def historical_auto_rate(
    session: Session, org_id: str, content_type: str, source_lang: str, target_lang: str
) -> float | None:
    since = utcnow() - timedelta(days=HISTORY_DAYS)
    auto, total = session.execute(
        select(
            func.coalesce(func.sum(Job.auto_approved_count), 0), func.coalesce(func.sum(Job.segment_count), 0)
        ).where(
            Job.org_id == org_id,
            Job.content_type == content_type,
            Job.source_lang == source_lang,
            Job.target_lang == target_lang,
            Job.created_at >= since,
            Job.segment_count > 0,
        )
    ).one()
    if not total:
        return None
    return min(1.0, max(0.0, float(auto) / float(total)))


def _eta(tier: str, words: int, auto_rate: float) -> float:
    machine = 0.1 + words / 50_000
    human_wph = REVIEW_WORDS_PER_HOUR * PARALLEL_REVIEWERS
    if tier == "auto":
        eta = machine
    elif tier == "ai_review":
        eta = machine + (1 - auto_rate) * words / 20_000
    elif tier == "hybrid":
        eta = machine + (1 - auto_rate) * words / human_wph
    else:
        eta = machine + words / human_wph
    return round(eta, 2)


def build_quote(
    session: Session,
    org: Organization,
    file_asset: FileAsset,
    target_langs: list[str],
    content_type: str = "general",
) -> Quote:
    """POST /quotes. Tenancy: the file must belong to the org."""
    if file_asset.org_id != org.id:
        raise Invalid("file not found")
    langs = list(dict.fromkeys(t.strip() for t in target_langs if t and t.strip()))
    if not langs:
        raise Invalid("at least one target language is required")
    if any(t.lower() == file_asset.source_lang.lower() for t in langs):
        raise Invalid("target language must differ from the source language")
    content_type = content_type or "general"
    segments = _segments(file_asset)
    word_count = sum(w for _, w in segments)
    weights = pricing.tm_weights(org)
    rates = pricing.tier_rates(org)
    minimum = pricing.minimum_charge(org)

    by_lang: dict[str, Any] = {}
    total_ww = Decimal("0")
    totals = dict.fromkeys(pricing.BANDS, 0)
    rate_num = 0.0
    for lang in langs:
        bands = analyse(session, org.id, file_asset.source_lang, lang, segments)
        ww = pricing.weighted_words(bands, weights)
        hist = historical_auto_rate(session, org.id, content_type, file_asset.source_lang, lang)
        auto_rate = AUTO_RATE_PRIOR if hist is None else hist
        by_lang[lang] = {
            "bands": bands,
            "weighted_words": str(ww.quantize(Decimal("0.1"))),
            "est_auto_rate": round(auto_rate, 3),
            "auto_rate_source": "prior" if hist is None else "history",
        }
        total_ww += ww
        for b, n in bands.items():
            totals[b] += n
        rate_num += auto_rate * max(word_count, 1)
    est_auto = rate_num / (max(word_count, 1) * len(langs))

    tiers: dict[str, Any] = {}
    for tier in pricing.TIERS:
        price = max(minimum, (total_ww * rates[tier]).quantize(CENT, rounding=ROUND_HALF_UP))
        tier_auto = 0.0 if tier == "full" else est_auto
        entry: dict[str, Any] = {
            "price": money(price),
            "rate_per_word": str(rates[tier]),
            "est_auto_rate": round(tier_auto, 3),
            "eta_hours": _eta(tier, word_count * len(langs), tier_auto),
            "available": True,
        }
        if org.regulated and tier in ("auto", "ai_review"):
            entry["available"] = False
            entry["blocked_reason"] = REGULATED_REASON
        tiers[tier] = entry

    analysis = {
        "tm_context": totals["context"],
        "tm_exact": totals["exact"],
        "tm_fuzzy": totals["fuzzy_95_99"] + totals["fuzzy_85_94"] + totals["fuzzy_75_84"],
        "new": totals["new"],
        "repetitions": totals["repetitions"],
        "bands": totals,
        "weighted_words": str(total_ww.quantize(Decimal("0.1"))),
        "by_lang": by_lang,
        "note": "Word counts are summed across target languages.",
    }
    quote = Quote(
        org_id=org.id,
        file_id=file_asset.id,
        source_lang=file_asset.source_lang,
        target_langs=langs,
        content_type=content_type,
        word_count=word_count,
        tiers=tiers,
        analysis=analysis,
        currency=get_settings().currency,
        status="open",
        valid_until=utcnow() + timedelta(days=get_settings().quote_validity_days),
    )
    session.add(quote)
    session.flush()
    return quote


def quote_view(quote: Quote) -> dict[str, Any]:
    """Quote per docs/api-contract.md."""
    return {
        "id": quote.id,
        "file_id": quote.file_id,
        "source_lang": quote.source_lang,
        "target_langs": list(quote.target_langs),
        "content_type": quote.content_type,
        "word_count": quote.word_count,
        "currency": quote.currency,
        "status": quote.status,
        "valid_until": quote.valid_until.isoformat(),
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
        "analysis": quote.analysis,
        "tiers": quote.tiers,
    }


def tier_allowed(quote: Quote, tier: str) -> bool:
    """For project creation: the tier exists in the quote and is available (R-SEG-12)."""
    entry = (quote.tiers or {}).get(tier)
    return bool(entry and entry.get("available"))


def expire_quotes(session: Session, now: datetime | None = None) -> int:
    """Open quotes past valid_until become expired. Returns how many (webhook quote.expired)."""
    now = now or utcnow()
    rows = list(
        session.execute(select(Quote).where(Quote.status == "open", Quote.valid_until < now)).scalars()
    )
    for q in rows:
        q.status = "expired"
    session.flush()
    return len(rows)

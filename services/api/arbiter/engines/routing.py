"""Engine routing (R-MT-02, D-058): which engines serve one call, in which order.

Precedence, first match wins and every later step only appends fallbacks:

    1. specific route    engine_routes row matching the job; the org's own rules beat
                         platform defaults, then the rule with more matching fields
                         (source_lang, target_lang, content_type) beats a general one
    2. general route     a rule with fewer fields (or none) for the same purpose
    3. scoreboard        engine_scores for the pair and domain (MT only)
    4. settings default  ARBITER_DEFAULT_MT_ENGINE / ARBITER_DEFAULT_JUDGE_ENGINE
    5. anything else available

A route with fallback=false stops after its own list. Senate and editor fall back to the
judge route when they have none of their own.

Then two hard filters, never relaxed:
  * processing region: an org with processing_region "eu" keeps only engines whose region
    is "eu" (or "local", the in-process mocks). Nothing left -> NoEngineInRegion: the job
    fails visibly with "no EU engine configured"; it never falls back to a non-EU engine.
  * budgets: providers at their monthly cap are dropped. Nothing left -> BudgetExceeded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError
from arbiter.engines import budgets, registry
from arbiter.engines.errors import BudgetExceeded, NoEngineInRegion
from arbiter.models import EngineRoute, EngineScore

PURPOSES = ("mt", "judge", "senate", "editor")
REGIONS = ("global", "eu")
EU_OK = {"eu", "local"}


def processing_region(org: Any) -> str:
    value = ((getattr(org, "settings", None) or {}).get("processing_region")) or "global"
    return value if value in REGIONS else "global"


def region_allows(processing: str, engine_region: str | None) -> bool:
    if engine_region is None:
        return False
    return processing != "eu" or engine_region in EU_OK


@dataclass
class RouteChoice:
    purpose: str
    region: str
    engines: list[str]
    source: str  # route | scoreboard | default | available
    route_id: str | None = None
    skipped: dict[str, str] = field(default_factory=dict)  # engine -> unavailable | region | budget

    def as_event(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "processing_region": self.region,
            "engines": self.engines,
            "source": self.source,
            "route_id": self.route_id,
            "skipped": self.skipped,
        }


def _specificity(r: EngineRoute) -> int:
    return sum(1 for v in (r.source_lang, r.target_lang, r.content_type) if v)


def matching_route(
    session: Session,
    org_id: str | None,
    purpose: str,
    source_lang: str | None,
    target_lang: str | None,
    content_type: str | None,
) -> EngineRoute | None:
    q = select(EngineRoute).where(EngineRoute.purpose == purpose, EngineRoute.enabled.is_(True))
    q = (
        q.where((EngineRoute.org_id == org_id) | EngineRoute.org_id.is_(None))
        if org_id
        else q.where(EngineRoute.org_id.is_(None))
    )
    rows = [
        r
        for r in session.execute(q).scalars()
        if (r.source_lang in (None, "", source_lang))
        and (r.target_lang in (None, "", target_lang))
        and (r.content_type in (None, "", content_type))
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda r: (
            r.org_id is not None,
            _specificity(r),
            r.created_at.timestamp() if r.created_at else 0,
        ),
        reverse=True,
    )
    return rows[0]


def scoreboard(
    session: Session, source_lang: str, target_lang: str, content_type: str, settings: Settings
) -> list[str]:
    rows = (
        session.execute(
            select(EngineScore)
            .where(
                EngineScore.source_lang == source_lang,
                EngineScore.target_lang == target_lang,
                EngineScore.domain.in_([content_type, "general"]),
            )
            .order_by(EngineScore.mean_qe.desc())
        )
        .scalars()
        .all()
    )
    out = []
    for b in rows:
        minimum = (
            settings.custom_model_min_eval_segments
            if b.engine.startswith(registry.CUSTOM_PREFIX)
            else settings.scoreboard_min_segments
        )
        if b.segments_measured >= minimum:
            out.append(b.engine)
    return out


RegionLookup = Callable[[str], "str | None"]


def default_region_lookup(purpose: str, settings: Settings, ctx: registry.EngineContext) -> RegionLookup:
    """Region of an engine by building its client (no network). None = cannot be built."""

    def lookup(name: str) -> str | None:
        try:
            if purpose == "mt":
                return registry.region_of(registry.get_mt(name, settings, context=ctx))
            return registry.region_of(registry.get_llm(name, settings, context=ctx))
        except EngineError:
            return None

    return lookup


def choose(
    session: Session,
    *,
    org: Any,
    purpose: str,
    source_lang: str | None = None,
    target_lang: str | None = None,
    content_type: str | None = "general",
    settings: Settings | None = None,
    context: registry.EngineContext | None = None,
    available: list[str] | None = None,
    region_lookup: RegionLookup | None = None,
) -> RouteChoice:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    s = settings or get_settings()
    org_id = getattr(org, "id", None)
    ctx = context or registry.EngineContext(session, org_id)
    region = processing_region(org)
    is_mt = purpose == "mt"
    default = s.default_mt_engine if is_mt else s.default_judge_engine
    if available is None:
        available = registry.available_mt(s, context=ctx) if is_mt else registry.available_llm(s, context=ctx)
        if not s.is_test and not default.startswith("mock"):
            available = [n for n in available if "mock" not in n]
    lookup = region_lookup or default_region_lookup(purpose, s, ctx)

    route = matching_route(session, org_id, purpose, source_lang, target_lang, content_type)
    if route is None and purpose in ("senate", "editor"):
        route = matching_route(session, org_id, "judge", source_lang, target_lang, content_type)
    ordered: list[str] = list(route.engines or []) if route else []
    source = "route" if route else "default"
    if route is None or route.fallback:
        board = (
            scoreboard(session, source_lang or "", target_lang or "", content_type or "general", s)
            if is_mt and source_lang and target_lang
            else []
        )
        if route is None and any(b in available for b in board):
            source = "scoreboard"
        rest = [n for n in available if n not in board and n != default]
        ordered += board + [default] + rest

    skipped: dict[str, str] = {}
    candidates: list[str] = []
    for name in dict.fromkeys(ordered):
        if name not in available:
            skipped[name] = "unavailable"
            continue
        candidates.append(name)
    if route is None and source == "default" and default not in candidates:
        source = "available"

    in_region = []
    for name in candidates:
        if region_allows(region, lookup(name)):
            in_region.append(name)
        else:
            skipped[name] = "region"
    if not in_region:
        if region == "eu":
            raise NoEngineInRegion(purpose, region)
        raise EngineError(f"no engine available for {purpose}")

    within_budget, capped = [], []
    for name in in_region:
        provider = registry.provider_of(name)
        if budgets.exceeded(session, org_id, provider):
            skipped[name] = "budget"
            capped.append(provider)
        else:
            within_budget.append(name)
    if not within_budget:
        raise BudgetExceeded(capped)
    return RouteChoice(purpose, region, within_budget, source, route.id if route else None, skipped)


def wrap_mt(engine: Any, session: Session, org_id: str | None) -> budgets.BudgetedMt:
    return budgets.BudgetedMt(engine, session, org_id, registry.provider_of(engine.name))


def wrap_llm(client: Any, session: Session, org_id: str | None) -> budgets.BudgetedLlm:
    return budgets.BudgetedLlm(client, session, org_id, registry.provider_of(client.name))

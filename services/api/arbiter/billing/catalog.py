"""Plans and credit packs: the catalog customers buy from (D-072).

The catalog is DATA in the plans and credit_packs tables, edited by the platform admin.
`STARTER_PLANS` and `STARTER_PACKS` below only seed an empty database (migration 0010 and
`python -m arbiter.cli seed-plans`); seeding never overwrites an existing row.

STARTING VALUES, not market-validated. The owner sets real prices before launch.

    plan        modules                                          month EUR   seats
    starter     tms, ai                                          49          2
    team        + pm, community                                  199         5
    business    + engine, auditor, strings                       599         15
    enterprise  every module, priced by contract (custom)        -           50

Plan JSON shapes (money and quantities are decimal strings):
    prices / seat_prices  {"month": {"EUR": "49.00"}, "year": {"EUR": "490.00"}}
    included              {"word": "50000", "ai_unit": "500"}   per billing month
    overage               {"EUR": {"word": "0.0150", "ai_unit": "0.0400"}}
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.billing.ledger import money
from arbiter.errors import Invalid, NotFound
from arbiter.models import CreditPack, Plan
from arbiter.platform.modules import MODULES

INTERVALS = ("month", "year")
METERED_UNITS = ("word", "ai_unit")
_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")

STARTER_PLANS: tuple[dict[str, Any], ...] = (
    {
        "key": "starter",
        "name": "Starter",
        "description": "Web translation with the AI quality layer for a small team.",
        "modules": ["tms", "ai"],
        "prices": {"month": {"EUR": "49.00", "USD": "55.00"}, "year": {"EUR": "490.00", "USD": "550.00"}},
        "seat_prices": {
            "month": {"EUR": "15.00", "USD": "17.00"},
            "year": {"EUR": "150.00", "USD": "170.00"},
        },
        "included": {"word": "50000", "ai_unit": "500"},
        "overage": {
            "EUR": {"word": "0.0150", "ai_unit": "0.0400"},
            "USD": {"word": "0.0170", "ai_unit": "0.0450"},
        },
        "seats_included": 2,
        "max_seats": 10,
        "sort": 10,
    },
    {
        "key": "team",
        "name": "Team",
        "description": "Adds project management and the reviewer marketplace.",
        "modules": ["tms", "ai", "pm", "community"],
        "prices": {"month": {"EUR": "199.00", "USD": "219.00"}, "year": {"EUR": "1990.00", "USD": "2190.00"}},
        "seat_prices": {
            "month": {"EUR": "19.00", "USD": "21.00"},
            "year": {"EUR": "190.00", "USD": "210.00"},
        },
        "included": {"word": "250000", "ai_unit": "2500"},
        "overage": {
            "EUR": {"word": "0.0120", "ai_unit": "0.0350"},
            "USD": {"word": "0.0135", "ai_unit": "0.0390"},
        },
        "seats_included": 5,
        "max_seats": 50,
        "sort": 20,
    },
    {
        "key": "business",
        "name": "Business",
        "description": "Adds the engine API, the quality auditor and software strings.",
        "modules": ["tms", "ai", "pm", "community", "engine", "auditor", "strings"],
        "prices": {"month": {"EUR": "599.00", "USD": "659.00"}, "year": {"EUR": "5990.00", "USD": "6590.00"}},
        "seat_prices": {
            "month": {"EUR": "25.00", "USD": "28.00"},
            "year": {"EUR": "250.00", "USD": "280.00"},
        },
        "included": {"word": "1000000", "ai_unit": "10000"},
        "overage": {
            "EUR": {"word": "0.0090", "ai_unit": "0.0300"},
            "USD": {"word": "0.0100", "ai_unit": "0.0330"},
        },
        "seats_included": 15,
        "max_seats": None,
        "sort": 30,
    },
    {
        "key": "enterprise",
        "name": "Enterprise",
        "description": "Every module, contract pricing, invoices with terms, PO and bank transfer.",
        "modules": list(MODULES),
        "prices": {},
        "seat_prices": {},
        "included": {},
        "overage": {},
        "seats_included": 50,
        "max_seats": None,
        "custom": True,
        "sort": 40,
    },
)

STARTER_PACKS: tuple[dict[str, Any], ...] = (
    {"key": "credits_50", "name": "Small", "credit_amount": "50.00", "price": "50.00", "sort": 10},
    {"key": "credits_200", "name": "Medium", "credit_amount": "210.00", "price": "200.00", "sort": 20},
    {"key": "credits_1000", "name": "Large", "credit_amount": "1080.00", "price": "1000.00", "sort": 30},
)


# ------------------------------------------------------------------ validation


def _dec(value: Any, what: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, float):
        raise Invalid(f"{what} must be a decimal string, not a float")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Invalid(f"{what} must be a decimal string") from None
    if not d.is_finite() or d < 0 or (not allow_zero and d == 0):
        raise Invalid(f"{what} must be a positive decimal")
    return d


def _currency(code: Any) -> str:
    c = str(code or "").upper()
    if len(c) != 3 or not c.isalpha():
        raise Invalid(f"invalid currency code {code!r}")
    return c


def _price_table(raw: Any, what: str) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise Invalid(f"{what} must be an object")
    out: dict[str, dict[str, str]] = {}
    for interval, by_cur in raw.items():
        if interval not in INTERVALS:
            raise Invalid(f"{what}: interval must be one of {', '.join(INTERVALS)}")
        if not isinstance(by_cur, dict):
            raise Invalid(f"{what}.{interval} must be an object of currency -> price")
        out[interval] = {_currency(c): money(_dec(v, f"{what}.{interval}.{c}")) for c, v in by_cur.items()}
    return out


def normalize_plan(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Validate an admin plan payload. Returns only the given fields, normalised."""
    out: dict[str, Any] = {}
    if "key" in data or not partial:
        key = str(data.get("key") or "").strip().lower()
        if not key or len(key) > 40 or not set(key) <= _KEY_CHARS:
            raise Invalid("key must be 1-40 characters of a-z, 0-9, _ or -")
        out["key"] = key
    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not name:
            raise Invalid("name is required")
        out["name"] = name[:120]
    if "description" in data:
        out["description"] = str(data.get("description") or "")[:500]
    if "modules" in data or not partial:
        mods = list(dict.fromkeys(data.get("modules") or []))
        unknown = [m for m in mods if m not in MODULES]
        if unknown:
            raise Invalid(f"unknown module(s): {', '.join(unknown)}", {"allowed": list(MODULES)})
        # A module that depends on another brings it along (strings, community need tms).
        for m in list(mods):
            for dep in MODULES[m]["depends_on"]:
                if dep not in mods:
                    mods.append(dep)
        out["modules"] = [m for m in MODULES if m in mods]
    for f in ("prices", "seat_prices"):
        if f in data:
            out[f] = _price_table(data.get(f), f)
    if "included" in data:
        inc = data.get("included") or {}
        if not isinstance(inc, dict):
            raise Invalid("included must be an object")
        bad = [u for u in inc if u not in METERED_UNITS]
        if bad:
            raise Invalid(f"included: unit must be one of {', '.join(METERED_UNITS)}")
        out["included"] = {u: format(_dec(v, f"included.{u}").normalize(), "f") for u, v in inc.items()}
    if "overage" in data:
        ov = data.get("overage") or {}
        if not isinstance(ov, dict):
            raise Invalid("overage must be an object")
        table: dict[str, dict[str, str]] = {}
        for cur, rates in ov.items():
            if not isinstance(rates, dict) or any(u not in METERED_UNITS for u in rates):
                raise Invalid(f"overage.{cur}: object of unit -> rate, units {', '.join(METERED_UNITS)}")
            table[_currency(cur)] = {u: str(_dec(r, f"overage.{cur}.{u}")) for u, r in rates.items()}
        out["overage"] = table
    for f in ("seats_included", "max_seats", "sort"):
        if f in data:
            v = data.get(f)
            if v is None and f == "max_seats":
                out[f] = None
                continue
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise Invalid(f"{f} must be a non-negative integer")
            out[f] = v
    if "interval" in data:
        if data["interval"] not in INTERVALS:
            raise Invalid(f"interval must be one of {', '.join(INTERVALS)}")
        out["interval"] = data["interval"]
    for f in ("custom", "public", "active"):
        if f in data:
            out[f] = bool(data[f])
    if "provider_prices" in data:
        pp = data.get("provider_prices") or {}
        if not isinstance(pp, dict) or not all(isinstance(v, dict) for v in pp.values()):
            raise Invalid('provider_prices must be {provider: {"interval:CUR": price_id}}')
        out["provider_prices"] = {p: {str(k): str(v) for k, v in m.items()} for p, m in pp.items()}
    ms, si = out.get("max_seats"), out.get("seats_included")
    if ms is not None and si is not None and ms < si:
        raise Invalid("max_seats must be at least seats_included")
    return out


# ------------------------------------------------------------------ reads and writes


def get_plan(session: Session, key: str, *, active_only: bool = True) -> Plan:
    plan = session.execute(select(Plan).where(Plan.key == key)).scalar_one_or_none()
    if plan is None or (active_only and not plan.active):
        raise NotFound("plan not found")
    return plan


def list_plans(session: Session, *, include_hidden: bool = False) -> list[Plan]:
    stmt = select(Plan).order_by(Plan.sort, Plan.key)
    if not include_hidden:
        stmt = stmt.where(Plan.active.is_(True), Plan.public.is_(True))
    return list(session.execute(stmt).scalars())


def create_plan(session: Session, data: dict[str, Any]) -> Plan:
    fields = normalize_plan(data)
    if session.execute(select(Plan.id).where(Plan.key == fields["key"])).first() is not None:
        from arbiter.errors import Conflict

        raise Conflict("a plan with this key exists")
    plan = Plan(**fields)
    session.add(plan)
    session.flush()
    return plan


def update_plan(session: Session, key: str, data: dict[str, Any]) -> Plan:
    plan = get_plan(session, key, active_only=False)
    fields = normalize_plan({k: v for k, v in data.items() if k != "key"}, partial=True)
    for k, v in fields.items():
        setattr(plan, k, v)
    if plan.max_seats is not None and plan.max_seats < plan.seats_included:
        raise Invalid("max_seats must be at least seats_included")
    session.flush()
    return plan


def plan_price(plan: Plan, interval: str, currency: str) -> Decimal | None:
    v = (plan.prices or {}).get(interval, {}).get(currency.upper())
    return Decimal(str(v)) if v is not None else None


def seat_price(plan: Plan, interval: str, currency: str) -> Decimal:
    v = (plan.seat_prices or {}).get(interval, {}).get(currency.upper())
    return Decimal(str(v)) if v is not None else Decimal("0")


def included(plan: Plan, unit: str) -> Decimal:
    v = (plan.included or {}).get(unit)
    return Decimal(str(v)) if v is not None else Decimal("0")


def overage_rate(plan: Plan, unit: str, currency: str) -> Decimal | None:
    v = (plan.overage or {}).get(currency.upper(), {}).get(unit)
    return Decimal(str(v)) if v is not None else None


def plan_view(plan: Plan, *, admin: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": plan.key,
        "name": plan.name,
        "description": plan.description,
        "modules": list(plan.modules or []),
        "prices": plan.prices or {},
        "seat_prices": plan.seat_prices or {},
        "included": plan.included or {},
        "overage": plan.overage or {},
        "seats_included": plan.seats_included,
        "max_seats": plan.max_seats,
        "interval": plan.interval,
        "custom": plan.custom,
        "currencies": sorted({c for by in (plan.prices or {}).values() for c in by}),
    }
    if admin:
        out.update(
            {
                "id": plan.id,
                "public": plan.public,
                "active": plan.active,
                "sort": plan.sort,
                "provider_prices": plan.provider_prices or {},
                "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
            }
        )
    return out


def get_pack(session: Session, key: str) -> CreditPack:
    pack = session.execute(select(CreditPack).where(CreditPack.key == key)).scalar_one_or_none()
    if pack is None or not pack.active:
        raise NotFound("credit pack not found")
    return pack


def list_packs(session: Session) -> list[CreditPack]:
    return list(
        session.execute(
            select(CreditPack).where(CreditPack.active.is_(True)).order_by(CreditPack.sort, CreditPack.key)
        ).scalars()
    )


def pack_view(pack: CreditPack) -> dict[str, Any]:
    return {
        "key": pack.key,
        "name": pack.name,
        "credit_amount": money(pack.credit_amount),
        "price": money(pack.price),
        "currency": pack.currency,
        "valid_days": pack.valid_days,
    }


def seed_starter_catalog(session: Session) -> dict[str, int]:
    """Insert the starter plans and packs that do not exist yet. Never overwrites."""
    plans = packs = 0
    have = set(session.execute(select(Plan.key)).scalars())
    for raw in STARTER_PLANS:
        if raw["key"] in have:
            continue
        fields = normalize_plan(raw)
        session.add(Plan(**fields))
        plans += 1
    have_packs = set(session.execute(select(CreditPack.key)).scalars())
    for raw in STARTER_PACKS:
        if raw["key"] in have_packs:
            continue
        session.add(
            CreditPack(
                key=raw["key"],
                name=raw["name"],
                credit_amount=Decimal(raw["credit_amount"]),
                price=Decimal(raw["price"]),
                currency="EUR",
                valid_days=365,
                active=True,
                sort=raw["sort"],
            )
        )
        packs += 1
    session.flush()
    return {"plans": plans, "packs": packs}

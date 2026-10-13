"""Engines for an organization (module "engine"): catalog, BYOK keys, routing rules, budgets.

Writes need the `engines.manage` permission (pm, admin). Keys are encrypted at rest and
never returned after save; responses carry `secret_hint` (last 4 characters) only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from arbiter.api.deps import DB, PM, Customer, require_module, require_permission
from arbiter.config import get_settings
from arbiter.contracts import EngineError
from arbiter.engines import catalog as cat
from arbiter.engines import credentials, manage, routing
from arbiter.engines.errors import RoutingBlocked
from arbiter.errors import Invalid
from arbiter.platform.modules import org_has_addon

router = APIRouter(tags=["engines"], dependencies=[require_module("engine")])
MANAGE = [require_permission("engines.manage")]


class CredentialIn(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    label: str = Field(default="", max_length=120)
    secret: dict[str, str] | str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class CredentialPatch(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    secret: dict[str, str] | str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class RouteIn(BaseModel):
    purpose: Literal["mt", "judge", "senate", "editor"] = "mt"
    source_lang: str | None = Field(default=None, max_length=16)
    target_lang: str | None = Field(default=None, max_length=16)
    content_type: str | None = Field(default=None, max_length=60)
    engines: list[str] = Field(min_length=1, max_length=10)
    fallback: bool = True
    enabled: bool = True
    note: str = Field(default="", max_length=300)


class RoutePatch(BaseModel):
    purpose: Literal["mt", "judge", "senate", "editor"] | None = None
    source_lang: str | None = Field(default=None, max_length=16)
    target_lang: str | None = Field(default=None, max_length=16)
    content_type: str | None = Field(default=None, max_length=60)
    engines: list[str] | None = Field(default=None, min_length=1, max_length=10)
    fallback: bool | None = None
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class BudgetIn(BaseModel):
    monthly_cap: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    enabled: bool = True


def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "next_offset": None}


def _byok(p: PM) -> None:
    if not org_has_addon(p.org, "byok"):
        raise Invalid("bring-your-own-key is not enabled for this organization")


# ------------------------------------------------------------------ catalog and preview


@router.get("/engines/catalog")
def engine_catalog(p: Customer, db: DB) -> dict[str, Any]:
    s = get_settings()
    org_id = p.org_id
    items = []
    for entry in cat.catalog():
        items.append({**entry, "configured": credentials.source_of(db, org_id, entry["provider"], s)})
    return {
        "items": items,
        "processing_region": routing.processing_region(p.org),
        "currency": s.currency,
        "note": "Prices are estimates per unit from list prices; the provider bill is the truth.",
    }


@router.get("/engines/preview")
def engine_preview(
    p: PM,
    db: DB,
    source_lang: str = Query(min_length=2, max_length=16),
    target_lang: str = Query(min_length=2, max_length=16),
    content_type: str = Query(default="general", max_length=60),
) -> dict[str, Any]:
    """Which engines a job for this pair would use right now, per purpose (or why none)."""
    out: dict[str, Any] = {}
    for purpose in routing.PURPOSES:
        try:
            choice = routing.choose(
                db,
                org=p.org,
                purpose=purpose,
                source_lang=source_lang,
                target_lang=target_lang,
                content_type=content_type,
            )
            out[purpose] = {"ok": True, **choice.as_event()}
        except RoutingBlocked as e:
            out[purpose] = {"ok": False, "code": e.code, "message": str(e)}
        except EngineError as e:
            out[purpose] = {"ok": False, "code": "no_engine", "message": str(e)}
    return {"processing_region": routing.processing_region(p.org), "purposes": out}


# ------------------------------------------------------------------ routes (rules)


@router.get("/engines/routes", dependencies=MANAGE)
def list_routes(p: PM, db: DB) -> dict[str, Any]:
    return _page([manage.route_view(r) for r in manage.list_routes(db, p.org_id)])


@router.post("/engines/routes", status_code=201, dependencies=MANAGE)
def create_route(body: RouteIn, p: PM, db: DB) -> dict[str, Any]:
    return manage.route_view(manage.create_route(db, p.org_id, body.model_dump()))


@router.patch("/engines/routes/{route_id}", dependencies=MANAGE)
def patch_route(route_id: str, body: RoutePatch, p: PM, db: DB) -> dict[str, Any]:
    r = manage.get_route(db, route_id, p.org_id)
    return manage.route_view(manage.update_route(r, body.model_dump(exclude_unset=True)))


@router.delete("/engines/routes/{route_id}", status_code=204, dependencies=MANAGE)
def delete_route(route_id: str, p: PM, db: DB) -> Response:
    db.delete(manage.get_route(db, route_id, p.org_id))
    return Response(status_code=204)


# ------------------------------------------------------------------ budgets


@router.get("/engines/budgets", dependencies=MANAGE)
def list_budgets(p: PM, db: DB) -> dict[str, Any]:
    from sqlalchemy import select

    from arbiter.models import EngineBudget

    rows = db.execute(
        select(EngineBudget).where(EngineBudget.org_id == p.org_id).order_by(EngineBudget.provider)
    ).scalars()
    return _page([manage.budget_view(b) for b in rows])


@router.put("/engines/budgets/{provider}", dependencies=MANAGE)
def put_budget(provider: str, body: BudgetIn, p: PM, db: DB) -> dict[str, Any]:
    if provider not in cat.PROVIDERS and provider != "custom":
        raise Invalid(f"unknown provider {provider!r}")
    return manage.budget_view(manage.upsert_budget(db, p.org_id, provider, body.monthly_cap, body.enabled))


@router.delete("/engines/budgets/{provider}", status_code=204, dependencies=MANAGE)
def delete_budget(provider: str, p: PM, db: DB) -> Response:
    from arbiter.engines import budgets
    from arbiter.errors import NotFound

    b = budgets.get(db, p.org_id, provider)
    if b is None:
        raise NotFound("budget not found")
    db.delete(b)
    return Response(status_code=204)


# ------------------------------------------------------------------ BYOK credentials


@router.get("/engines", dependencies=MANAGE)
def list_credentials(p: PM, db: DB) -> dict[str, Any]:
    rows = manage.list_credentials(db, scope="org", org_id=p.org_id)
    return _page([manage.credential_view(c) for c in rows])


@router.post("/engines", status_code=201, dependencies=MANAGE)
def create_credential(body: CredentialIn, p: PM, db: DB) -> dict[str, Any]:
    _byok(p)
    cred = manage.create_credential(
        db,
        scope="org",
        org_id=p.org_id,
        provider=body.provider,
        label=body.label,
        secret=body.secret,
        config=body.config,
        enabled=body.enabled,
        actor=p.user.id if p.user else None,
    )
    return manage.credential_view(cred)


@router.patch("/engines/{cred_id}", dependencies=MANAGE)
def patch_credential(cred_id: str, body: CredentialPatch, p: PM, db: DB) -> dict[str, Any]:
    cred = manage.get_credential(db, cred_id, scope="org", org_id=p.org_id)
    return manage.credential_view(manage.update_credential(db, cred, body.model_dump(exclude_unset=True)))


@router.delete("/engines/{cred_id}", status_code=204, dependencies=MANAGE)
def delete_credential(cred_id: str, p: PM, db: DB) -> Response:
    db.delete(manage.get_credential(db, cred_id, scope="org", org_id=p.org_id))
    return Response(status_code=204)


@router.post("/engines/{cred_id}/test", dependencies=MANAGE)
def test_credential(cred_id: str, p: PM, db: DB) -> dict[str, Any]:
    return manage.test_credential(db, manage.get_credential(db, cred_id, scope="org", org_id=p.org_id))

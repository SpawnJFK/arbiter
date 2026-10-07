"""Dashboards (Agency OS). Writes: pm or API key; reads also for the client role (money hidden)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header
from sqlalchemy import select

from arbiter.agency import dashboards as dsh
from arbiter.agency.schemas import DashboardIn, DashboardPatch
from arbiter.api.deps import DB, PM, Customer, Paging, Principal, listing
from arbiter.api.routes.projects import idempotent_post
from arbiter.models import Dashboard

router = APIRouter(tags=["dashboards"])


def _uid(p: Principal) -> str | None:
    return p.user.id if p.user is not None else None


@router.get("/dashboards")
def list_dashboards(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(Dashboard)
            .where(Dashboard.org_id == p.org_id)
            .order_by(Dashboard.is_default.desc(), Dashboard.created_at, Dashboard.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([dsh.dashboard_view(d) for d in rows], pg)


@router.post("/dashboards", status_code=201)
def create_dashboard(
    body: DashboardIn, p: PM, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    def make() -> dict[str, Any]:
        return dsh.dashboard_view(dsh.create_dashboard(db, p.org_id, body, _uid(p)))

    return idempotent_post(db, p, "dashboards", idempotency_key, body.model_dump(mode="json"), make)


@router.get("/dashboards/default")
def default_dashboard(p: Customer, db: DB) -> dict[str, Any]:
    """The org's default dashboard; created on the first call."""
    return dsh.dashboard_view(dsh.default_dashboard(db, p.org_id, _uid(p)))


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str, p: Customer, db: DB) -> dict[str, Any]:
    return dsh.dashboard_view(dsh.get_dashboard(db, p.org_id, dashboard_id))


@router.patch("/dashboards/{dashboard_id}")
def patch_dashboard(dashboard_id: str, body: DashboardPatch, p: PM, db: DB) -> dict[str, Any]:
    return dsh.dashboard_view(dsh.update_dashboard(db, dsh.get_dashboard(db, p.org_id, dashboard_id), body))


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: str, p: PM, db: DB) -> dict[str, Any]:
    """Deletes and returns the dashboard as it was (the default one is recreated on demand)."""
    d = dsh.get_dashboard(db, p.org_id, dashboard_id)
    out = dsh.dashboard_view(d)
    db.delete(d)
    return out


@router.get("/dashboards/{dashboard_id}/data")
def dashboard_data(
    dashboard_id: str, p: Customer, db: DB, period: Literal["30d", "90d", "365d"] = "30d"
) -> dict[str, Any]:
    d = dsh.get_dashboard(db, p.org_id, dashboard_id)
    return dsh.dashboard_data(db, p.org_id, d, period, hide_money=p.role == "client")

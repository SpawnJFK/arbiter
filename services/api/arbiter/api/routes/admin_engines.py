"""Platform engine keys and platform default routes (platform admin only).

A platform key serves every organization that has no key of its own for that provider
(resolution: org BYOK > platform key > environment). Platform routes apply to every org
without a more specific rule of its own.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from arbiter.api.deps import DB, Admin
from arbiter.api.routes.engines import CredentialIn, CredentialPatch, RouteIn, RoutePatch
from arbiter.engines import manage

router = APIRouter(prefix="/admin", tags=["admin"])


def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "next_offset": None}


@router.get("/engines/catalog")
def platform_catalog(_: Admin, db: DB) -> dict[str, Any]:
    """The catalog as the platform sees it: `configured` is platform, env or none."""
    from arbiter.config import get_settings
    from arbiter.engines import catalog, credentials

    s = get_settings()
    items = [
        {**e, "configured": credentials.source_of(db, None, e["provider"], s)} for e in catalog.catalog()
    ]
    return {"items": items, "processing_region": "global", "currency": s.currency, "note": ""}


@router.get("/engines/routes")
def list_platform_routes(_: Admin, db: DB) -> dict[str, Any]:
    return _page([manage.route_view(r) for r in manage.list_routes(db, None)])


@router.post("/engines/routes", status_code=201)
def create_platform_route(body: RouteIn, _: Admin, db: DB) -> dict[str, Any]:
    return manage.route_view(manage.create_route(db, None, body.model_dump()))


@router.patch("/engines/routes/{route_id}")
def patch_platform_route(route_id: str, body: RoutePatch, _: Admin, db: DB) -> dict[str, Any]:
    r = manage.get_route(db, route_id, None)
    return manage.route_view(manage.update_route(r, body.model_dump(exclude_unset=True)))


@router.delete("/engines/routes/{route_id}", status_code=204)
def delete_platform_route(route_id: str, _: Admin, db: DB) -> Response:
    db.delete(manage.get_route(db, route_id, None))
    return Response(status_code=204)


@router.get("/engines")
def list_platform_credentials(_: Admin, db: DB) -> dict[str, Any]:
    rows = manage.list_credentials(db, scope="platform", org_id=None)
    return _page([manage.credential_view(c) for c in rows])


@router.post("/engines", status_code=201)
def create_platform_credential(body: CredentialIn, p: Admin, db: DB) -> dict[str, Any]:
    cred = manage.create_credential(
        db,
        scope="platform",
        org_id=None,
        provider=body.provider,
        label=body.label,
        secret=body.secret,
        config=body.config,
        enabled=body.enabled,
        actor=p.user.id if p.user else None,
    )
    return manage.credential_view(cred)


@router.patch("/engines/{cred_id}")
def patch_platform_credential(cred_id: str, body: CredentialPatch, _: Admin, db: DB) -> dict[str, Any]:
    cred = manage.get_credential(db, cred_id, scope="platform", org_id=None)
    return manage.credential_view(manage.update_credential(db, cred, body.model_dump(exclude_unset=True)))


@router.delete("/engines/{cred_id}", status_code=204)
def delete_platform_credential(cred_id: str, _: Admin, db: DB) -> Response:
    db.delete(manage.get_credential(db, cred_id, scope="platform", org_id=None))
    return Response(status_code=204)


@router.post("/engines/{cred_id}/test")
def test_platform_credential(cred_id: str, _: Admin, db: DB) -> dict[str, Any]:
    return manage.test_credential(db, manage.get_credential(db, cred_id, scope="platform", org_id=None))

"""Platform endpoints: module entitlements, custom roles, team, audit log, OpenID Connect SSO.

None of these are module-gated: they are the platform every module runs on. Fine-grained
access uses require_permission (built-in role or custom role); changes that hand out access
also need a signed-in user (UserOnly), never an API key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from arbiter.api import security
from arbiter.api.deps import DB, Admin, Customer, Paging, Principal, UserOnly, listing, require_permission
from arbiter.api.routes.auth import org_view, user_view
from arbiter.config import get_settings
from arbiter.errors import Invalid, NotFound
from arbiter.models import Organization
from arbiter.platform import audit as audit_log
from arbiter.platform import modules as mods
from arbiter.platform import sso, team
from arbiter.platform.permissions import PERMISSION_CATALOG

router = APIRouter(tags=["platform"])


def _perm(name: str) -> Any:
    return Annotated[Principal, require_permission(name)]


UsersRead = _perm("users.read")
UsersWrite = _perm("users.write")
RolesWrite = _perm("roles.write")
AuditRead = _perm("audit.read")
OrgManage = _perm("org.manage")


# ------------------------------------------------------------------ modules


@router.get("/org/modules")
def org_modules(p: Customer) -> dict[str, Any]:
    assert p.org is not None
    return {"enabled": mods.effective_modules(p.org), "catalog": mods.catalog(p.org)}


def _org(db: DB, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound("organization not found")
    return org


@router.get("/admin/orgs/{org_id}")
def admin_org(org_id: str, _: Admin, db: DB) -> dict[str, Any]:
    org = _org(db, org_id)
    return {**org_view(org), "kind": org.kind, "catalog": mods.catalog(org)}


class ModulesIn(BaseModel):
    modules: list[str] = Field(max_length=50)


@router.put("/admin/orgs/{org_id}/modules")
def set_modules(org_id: str, body: ModulesIn, p: Admin, db: DB) -> dict[str, Any]:
    org = _org(db, org_id)
    problems = mods.module_problems(body.modules)
    if problems:
        raise Invalid("module list is not valid", {"problems": problems})
    before = mods.effective_modules(org)
    stored = mods.set_org_modules(org, body.modules)
    db.flush()
    audit_log.audit(
        db, p, "module.changed", "organization", org.id, {"from": before, "to": stored}, org_id=org.id
    )
    return {"enabled": mods.effective_modules(org), "catalog": mods.catalog(org)}


# ------------------------------------------------------------------ roles


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    base_role: Literal["pm", "client"] = "client"
    permissions: list[str] = Field(default_factory=list, max_length=100)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    base_role: Literal["pm", "client"] | None = None
    permissions: list[str] | None = Field(default=None, max_length=100)


@router.get("/roles")
def list_roles(p: UsersRead, db: DB) -> dict[str, Any]:
    return {
        "items": team.list_roles(db, p.org_id),
        "next_offset": None,
        "builtin": [{"key": "pm"}, {"key": "client"}],
        "catalog": [{"key": k, "description": v} for k, v in PERMISSION_CATALOG.items()],
    }


@router.post("/roles", status_code=201)
def create_role(body: RoleIn, p: RolesWrite, _: UserOnly, db: DB) -> dict[str, Any]:
    return team.create_role(db, p, body.model_dump())


@router.patch("/roles/{role_id}")
def patch_role(role_id: str, body: RolePatch, p: RolesWrite, _: UserOnly, db: DB) -> dict[str, Any]:
    return team.update_role(db, p, role_id, body.model_dump(exclude_unset=True))


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: str, p: RolesWrite, _: UserOnly, db: DB) -> Response:
    team.delete_role(db, p, role_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ team


@router.get("/users")
def list_users(p: UsersRead, db: DB, pg: Paging) -> dict[str, Any]:
    return listing(team.list_members(db, p.org_id, pg.offset, pg.limit + 1), pg)


class InviteIn(BaseModel):
    email: EmailStr
    name: str = Field(default="", max_length=200)
    role: Literal["pm", "client"] | None = None
    role_id: str | None = Field(default=None, max_length=40)


@router.post("/users/invite", status_code=201)
def invite(body: InviteIn, p: UsersWrite, _: UserOnly, db: DB) -> dict[str, Any]:
    return team.invite_member(db, p, body.model_dump())


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: Literal["pm", "client"] | None = None
    role_id: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, p: UsersWrite, _: UserOnly, db: DB) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "role_id" in data and data["role_id"] is None and data.get("role") is None:
        # Clearing the custom role keeps the member's current base role.
        data["role"] = team.get_member(db, p.org_id, user_id).role
    return team.update_member(db, p, user_id, data)


@router.delete("/users/{user_id}", status_code=204)
def deactivate_user(user_id: str, p: UsersWrite, _: UserOnly, db: DB) -> Response:
    team.deactivate_member(db, p, user_id)
    return Response(status_code=204)


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=200)


@router.post("/auth/invite/accept")
def accept_invite(body: AcceptInviteIn, db: DB) -> dict[str, Any]:
    user = team.accept_invite(db, body.token, body.password, body.name)
    return {"token": security.issue_token(user.id, user.role, user.org_id), "user": user_view(user)}


# ------------------------------------------------------------------ audit log


@router.get("/audit")
def list_audit(
    p: AuditRead,
    db: DB,
    pg: Paging,
    actor: Annotated[str | None, Query(max_length=320)] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    q = audit_log.query(p.org_id, actor, action, since, until).offset(pg.offset).limit(pg.limit + 1)
    return listing([audit_log.event_view(e) for e in db.execute(q).scalars()], pg)


@router.get("/audit/export")
def export_audit(
    p: AuditRead,
    db: DB,
    actor: Annotated[str | None, Query(max_length=320)] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    cap = get_settings().audit_export_max_rows
    rows = db.execute(audit_log.query(p.org_id, actor, action, since, until).limit(cap)).scalars()
    body = audit_log.to_csv(rows)
    audit_log.audit(db, p, "audit.exported", "audit_log", p.org_id, {"actor": actor, "action": action})
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


# ------------------------------------------------------------------ SSO


class SsoIn(BaseModel):
    issuer: str = Field(min_length=8, max_length=500)
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str | None = Field(default=None, max_length=2000)
    allowed_domains: list[str] = Field(default_factory=list, max_length=50)
    default_role: Literal["pm", "client"] = "client"
    default_role_id: str | None = Field(default=None, max_length=40)
    enforce_sso: bool = False
    enabled: bool = True


@router.get("/org/sso")
def get_sso(p: OrgManage, db: DB) -> dict[str, Any]:
    return sso.config_view(db, p.org_id)


@router.put("/org/sso")
def put_sso(body: SsoIn, p: OrgManage, _: UserOnly, db: DB) -> dict[str, Any]:
    return sso.save_config(db, p, body.model_dump())


@router.delete("/org/sso", status_code=204)
def delete_sso(p: OrgManage, _: UserOnly, db: DB) -> Response:
    sso.delete_config(db, p)
    return Response(status_code=204)


@router.post("/org/sso/domains/{domain}/verify")
def verify_sso_domain(domain: str, p: OrgManage, _: UserOnly, db: DB) -> dict[str, Any]:
    return sso.verify_domain(db, p, domain)


@router.post("/admin/sso-domains/{domain}/verify")
def admin_verify_sso_domain(domain: str, p: Admin, db: DB) -> dict[str, Any]:
    return sso.verify_domain(db, p, domain, by_admin=True)


@router.get("/auth/sso/check")
def sso_check(email: Annotated[str, Query(min_length=3, max_length=320)], db: DB) -> dict[str, Any]:
    """Whether the login page should offer (or require) single sign-on for this email."""
    try:
        cfg, _org = sso.active_config_for(db, email.lower())
    except NotFound:
        return {"sso": False, "enforced": False}
    return {"sso": True, "enforced": cfg.enforce_sso}


@router.get("/auth/sso/start")
def sso_start(
    email: Annotated[str, Query(min_length=3, max_length=320)],
    db: DB,
    next: Annotated[str | None, Query(max_length=500)] = None,
) -> RedirectResponse:
    return RedirectResponse(sso.start_login(db, email.lower(), next), status_code=302)


@router.get("/auth/sso/callback")
def sso_callback(
    code: Annotated[str, Query(min_length=1, max_length=4000)],
    state: Annotated[str, Query(min_length=1, max_length=200)],
    db: DB,
) -> dict[str, Any]:
    user, next_path = sso.complete_login(db, code, state)
    return {
        "token": security.issue_token(user.id, user.role, user.org_id),
        "user": user_view(user),
        "redirect": next_path or None,
    }

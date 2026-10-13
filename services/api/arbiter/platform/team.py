"""Team management: custom roles, members, invites. Called by api/routes/platform.py.

Guards against privilege escalation:
  * a role can only grant permissions the acting user holds (permissions.cannot_grant);
  * only a user whose base role is pm may create pm-based roles or make someone a pm;
  * nobody changes their own role or deactivates themselves;
  * the last active pm of an organization cannot be demoted or deactivated (no lockout).
Every change writes an audit event in the same transaction.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import secrets
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.errors import Conflict, Forbidden, Invalid, NotFound
from arbiter.models import Organization, Role, SsoConfig, User, UserInvite, utcnow
from arbiter.platform import permissions as perms
from arbiter.platform.audit import audit

log = logging.getLogger("arbiter.platform.team")

BASE_ROLES = ("pm", "client")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def unusable_password_hash() -> str:
    """A hash nobody knows the password for (invited or SSO-provisioned users)."""
    from arbiter.api.security import hash_password

    return hash_password(secrets.token_urlsafe(32))


# ------------------------------------------------------------------ roles


def role_view(r: Role, members: int = 0) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "base_role": r.base_role,
        "permissions": list(r.permissions or []),
        "members": members,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _check_grant(actor: Any, base_role: str, permissions: list[str]) -> list[str]:
    if base_role not in BASE_ROLES:
        raise Invalid("base_role must be pm or client")
    cleaned = sorted({p.strip() for p in permissions if p.strip()})
    bad = [p for p in cleaned if not perms.is_valid_permission(p)]
    if bad:
        raise Invalid("invalid permission names", {"permissions": bad})
    missing = perms.cannot_grant(actor, cleaned)
    if missing:
        raise Forbidden("you cannot grant permissions you do not hold", {"permissions": missing})
    if base_role == "pm" and actor.role not in ("pm", "admin"):
        raise Forbidden("only a project manager can create or assign pm-based roles")
    return cleaned


def get_role(db: Session, org_id: str, role_id: str) -> Role:
    r = db.get(Role, role_id)
    if r is None or r.org_id != org_id:
        raise NotFound("role not found")
    return r


def member_counts(db: Session, org_id: str) -> dict[str, int]:
    rows = db.execute(
        select(User.role_id, func.count(User.id))
        .where(User.org_id == org_id, User.role_id.is_not(None), User.is_active.is_(True))
        .group_by(User.role_id)
    ).all()
    return {rid: int(n) for rid, n in rows}


def list_roles(db: Session, org_id: str) -> list[dict[str, Any]]:
    counts = member_counts(db, org_id)
    roles = db.execute(select(Role).where(Role.org_id == org_id).order_by(Role.name)).scalars()
    return [role_view(r, counts.get(r.id, 0)) for r in roles]


def _name_free(db: Session, org_id: str, name: str, except_id: str | None = None) -> None:
    q = select(Role.id).where(Role.org_id == org_id, func.lower(Role.name) == name.lower())
    found = db.execute(q).scalar_one_or_none()
    if found and found != except_id:
        raise Conflict("a role with this name already exists")


def create_role(db: Session, actor: Any, data: dict[str, Any]) -> dict[str, Any]:
    org_id = actor.org_id
    name = data["name"].strip()
    _name_free(db, org_id, name)
    granted = _check_grant(actor, data.get("base_role", "client"), data.get("permissions", []))
    r = Role(
        org_id=org_id,
        name=name,
        description=data.get("description", ""),
        base_role=data.get("base_role", "client"),
        permissions=granted,
    )
    db.add(r)
    db.flush()
    audit(
        db,
        actor,
        "role.created",
        "role",
        r.id,
        {"name": r.name, "base_role": r.base_role, "permissions": granted},
    )
    return role_view(r)


def update_role(db: Session, actor: Any, role_id: str, data: dict[str, Any]) -> dict[str, Any]:
    r = get_role(db, actor.org_id, role_id)
    before = role_view(r)
    if data.get("name") is not None:
        _name_free(db, actor.org_id, data["name"].strip(), except_id=r.id)
        r.name = data["name"].strip()
    if data.get("description") is not None:
        r.description = data["description"]
    base = data.get("base_role") or r.base_role
    if data.get("permissions") is not None or data.get("base_role") is not None:
        new_perms = data["permissions"] if data.get("permissions") is not None else list(r.permissions or [])
        r.permissions = _check_grant(actor, base, new_perms)
        if base != r.base_role:
            r.base_role = base
            for u in db.execute(select(User).where(User.role_id == r.id)).scalars():
                _guard_last_pm(db, u, new_role=base, new_active=u.is_active)
                u.role = base
    db.flush()
    after = role_view(r, member_counts(db, actor.org_id).get(r.id, 0))
    changes = {
        k: {"from": before[k], "to": after[k]}
        for k in ("name", "base_role", "permissions", "description")
        if before[k] != after[k]
    }
    audit(db, actor, "role.updated", "role", r.id, {"changes": changes})
    return after


def delete_role(db: Session, actor: Any, role_id: str) -> None:
    r = get_role(db, actor.org_id, role_id)
    in_use = db.execute(select(func.count(User.id)).where(User.role_id == r.id)).scalar_one()
    if in_use:
        raise Conflict("the role is assigned to team members; reassign them first", {"members": int(in_use)})
    cfg = db.get(SsoConfig, actor.org_id)
    if cfg is not None and cfg.default_role_id == r.id:
        raise Conflict("the role is the SSO default role; change the SSO settings first")
    audit(db, actor, "role.deleted", "role", r.id, {"name": r.name})
    db.delete(r)


# ------------------------------------------------------------------ members


def _pending_invites(db: Session, user_ids: list[str]) -> set[str]:
    if not user_ids:
        return set()
    rows = db.execute(
        select(UserInvite.user_id).where(
            UserInvite.user_id.in_(user_ids), UserInvite.used_at.is_(None), UserInvite.expires_at > utcnow()
        )
    ).scalars()
    return set(rows)


def member_view(u: User, roles: dict[str, Role], pending: set[str]) -> dict[str, Any]:
    status = "deactivated" if not u.is_active else ("invited" if u.id in pending else "active")
    custom = roles.get(u.role_id) if u.role_id else None
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "role_id": u.role_id,
        "role_name": custom.name if custom else None,
        "status": status,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def list_members(db: Session, org_id: str, offset: int, limit: int) -> list[dict[str, Any]]:
    users = list(
        db.execute(
            select(User)
            .where(User.org_id == org_id)
            .order_by(User.created_at, User.id)
            .offset(offset)
            .limit(limit)
        ).scalars()
    )
    roles = {r.id: r for r in db.execute(select(Role).where(Role.org_id == org_id)).scalars()}
    pending = _pending_invites(db, [u.id for u in users])
    return [member_view(u, roles, pending) for u in users]


def one_member(db: Session, u: User) -> dict[str, Any]:
    roles = {r.id: r for r in db.execute(select(Role).where(Role.org_id == u.org_id)).scalars()}
    return member_view(u, roles, _pending_invites(db, [u.id]))


def get_member(db: Session, org_id: str, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None or u.org_id != org_id:
        raise NotFound("user not found")
    return u


def _guard_last_pm(db: Session, u: User, new_role: str, new_active: bool) -> None:
    if u.role != "pm" or not u.is_active or (new_role == "pm" and new_active):
        return
    others = db.execute(
        select(func.count(User.id)).where(
            User.org_id == u.org_id, User.role == "pm", User.is_active.is_(True), User.id != u.id
        )
    ).scalar_one()
    if not others:
        raise Conflict("an organization needs at least one active project manager")


def _resolve_role(db: Session, actor: Any, role: str | None, role_id: str | None) -> tuple[str, str | None]:
    """(base role, custom role id) for an assignment, with the escalation checks."""
    if role_id:
        r = get_role(db, actor.org_id, role_id)
        _check_grant(actor, r.base_role, list(r.permissions or []))
        return r.base_role, r.id
    base = role or "client"
    if base not in BASE_ROLES:
        raise Invalid("role must be pm or client")
    if base == "pm" and actor.role not in ("pm", "admin"):
        raise Forbidden("only a project manager can make someone a project manager")
    return base, None


def update_member(db: Session, actor: Any, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    u = get_member(db, actor.org_id, user_id)
    changes: dict[str, Any] = {}
    touches_access = any(k in data for k in ("role", "role_id", "is_active"))
    if touches_access and actor.user is not None and actor.user.id == u.id:
        raise Invalid("you cannot change your own role or deactivate yourself")
    if "role" in data or "role_id" in data:
        base, rid = _resolve_role(db, actor, data.get("role"), data.get("role_id"))
        _guard_last_pm(db, u, new_role=base, new_active=u.is_active)
        if (base, rid) != (u.role, u.role_id):
            changes["role"] = {"from": [u.role, u.role_id], "to": [base, rid]}
            u.role, u.role_id = base, rid
    if data.get("is_active") is not None and data["is_active"] != u.is_active:
        _guard_last_pm(db, u, new_role=u.role, new_active=data["is_active"])
        changes["is_active"] = {"from": u.is_active, "to": data["is_active"]}
        u.is_active = data["is_active"]
    if data.get("name") is not None and data["name"] != u.name:
        changes["name"] = {"from": u.name, "to": data["name"]}
        u.name = data["name"]
    db.flush()
    if changes:
        action = "user.deactivated" if changes.get("is_active", {}).get("to") is False else "user.updated"
        if changes.get("is_active", {}).get("to") is True:
            action = "user.reactivated"
        audit(db, actor, action, "user", u.id, {"email": u.email, "changes": changes})
    return one_member(db, u)


def deactivate_member(db: Session, actor: Any, user_id: str) -> dict[str, Any]:
    return update_member(db, actor, user_id, {"is_active": False})


# ------------------------------------------------------------------ invites


def _deliver_invite(org: Organization, user: User, url: str, inviter: Any) -> bool:
    """Send the invite email through arbiter.notify when that package exists
    (expected: `send_invite_email(to=, url=, org_name=, inviter_name=)`). Returns True if sent.
    Without it the invite is only logged; the link itself is logged in dev and test only."""
    try:
        notify = importlib.import_module("arbiter.notify")
    except ImportError:
        notify = None
    sender = getattr(notify, "send_invite_email", None) if notify else None
    if sender is not None:
        sender(to=user.email, url=url, org_name=org.name, inviter_name=getattr(inviter.user, "name", ""))
        return True
    if get_settings().env in ("dev", "test"):
        log.info("invite for %s (%s): %s", user.email, org.name, url)
    else:
        log.warning("invite for %s created but no email sender is configured", user.email)
    return False


def invite_member(db: Session, actor: Any, data: dict[str, Any]) -> dict[str, Any]:
    email = data["email"].strip().lower()
    if db.execute(select(User.id).where(func.lower(User.email) == email)).scalar_one_or_none():
        raise Conflict("an account with this email already exists")
    base, rid = _resolve_role(db, actor, data.get("role"), data.get("role_id"))
    s = get_settings()
    user = User(
        email=email,
        name=data.get("name", ""),
        password_hash=unusable_password_hash(),
        role=base,
        role_id=rid,
        org_id=actor.org_id,
    )
    db.add(user)
    db.flush()
    token = secrets.token_urlsafe(32)
    inv = UserInvite(
        org_id=actor.org_id,
        user_id=user.id,
        token_hash=token_hash(token),
        invited_by=actor.user.id if actor.user else None,
        expires_at=utcnow() + timedelta(hours=s.invite_ttl_hours),
    )
    db.add(inv)
    db.flush()
    url = f"{s.web_base_url.rstrip('/')}/accept-invite?token={token}"
    sent = _deliver_invite(actor.org, user, url, actor)
    audit(
        db,
        actor,
        "user.invited",
        "user",
        user.id,
        {"email": email, "role": base, "role_id": rid, "email_sent": sent},
    )
    out: dict[str, Any] = {
        "user": one_member(db, user),
        "expires_at": inv.expires_at.isoformat(),
        "email_sent": sent,
    }
    if s.env in ("dev", "test"):  # never expose the one-time token in staging or prod
        out["invite_token"] = token
        out["invite_url"] = url
    return out


def accept_invite(db: Session, token: str, password: str, name: str | None) -> User:
    from arbiter.api.security import hash_password

    inv = db.execute(
        select(UserInvite).where(UserInvite.token_hash == token_hash(token))
    ).scalar_one_or_none()
    if inv is None or inv.used_at is not None or inv.expires_at <= utcnow():
        raise NotFound("this invite link is invalid or has expired")
    user = db.get(User, inv.user_id)
    if user is None or not user.is_active:
        raise NotFound("this invite link is invalid or has expired")
    user.password_hash = hash_password(password)
    if name:
        user.name = name
    inv.used_at = utcnow()
    org = db.get(Organization, user.org_id) if user.org_id else None
    who = SimpleNamespace(user=user, api_key=None, org=org)
    audit(db, who, "user.invite_accepted", "user", user.id, {"email": user.email})
    return user

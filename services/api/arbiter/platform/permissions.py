"""Permissions SEAM. Fine-grained checks layered on top of the coarse roles in api/deps.py.

Permission strings are "<area>.<action>", e.g. "jobs.read", "jobs.write", "billing.manage",
"engines.manage", "vendors.manage", "audit.read". Routes call `has_permission(principal, perm)`
or use `require_permission(perm)` from arbiter.api.deps.

A user with a custom role (models.platform.Role) carries that role's permissions on the
Principal (`principal.permissions`, a list); they replace the built-in set of the user's base
role. Everyone else gets the built-in mapping below. Permissions in EXPLICIT_ONLY are never
granted by a cross-area wildcard ("*.read"): the audit log is not "just another read".
"""

from __future__ import annotations

import re
from typing import Any

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "pm": {
        "*.read",
        "*.write",
        "billing.manage",
        "engines.manage",
        "vendors.manage",
        "audit.read",
        "org.manage",
        "strings.publish",
    },
    "api": {"*.read", "*.write", "strings.publish"},
    "client": {"*.read", "jobs.write", "files.write", "quotes.write"},
    "reviewer": {"tasks.read", "tasks.write"},
}

# Only "*", the exact string or "<area>.*" grant these.
EXPLICIT_ONLY: frozenset[str] = frozenset({"audit.read"})

# Known permissions, shown in the role editor. Patterns with "*" are valid too ("jobs.*",
# "*.read"). Routes may check permissions that are not listed; listing them documents them.
PERMISSION_CATALOG: dict[str, str] = {
    "projects.read": "See projects, jobs and segments",
    "projects.write": "Create projects, upload files, request quotes",
    "jobs.read": "See jobs, segments and evidence packs",
    "jobs.write": "Edit and approve segments, cancel jobs",
    "files.write": "Upload source files",
    "quotes.write": "Request quotes",
    "assets.read": "See glossaries, translation memory and term questions",
    "assets.write": "Edit glossaries, import glossaries and translation memory",
    "quality.read": "See the quality dashboard and thresholds",
    "crm.read": "See CRM accounts, contacts, deals and activities",
    "crm.write": "Edit CRM records",
    "pricelists.write": "Edit price lists",
    "workflows.write": "Edit workflow templates",
    "dashboards.write": "Edit dashboards",
    "assistant.write": "Use the AI project assistant",
    "billing.read": "See usage and invoices",
    "billing.manage": "Manage plans and payment details",
    "engines.manage": "Manage translation engines and provider keys",
    "vendors.manage": "Manage vendors",
    "org.manage": "Change organization settings, webhooks, API keys and SSO",
    "users.read": "See team members",
    "users.write": "Invite, change and deactivate team members",
    "roles.write": "Create and change custom roles",
    "audit.read": "See and export the audit log",
}

_PERM_RE = re.compile(r"^(\*|[a-z][a-z0-9_]*)\.(\*|[a-z][a-z0-9_]*)$")


def _match(granted: str, perm: str) -> bool:
    if granted in ("*", perm):
        return True
    g_area, _, g_action = granted.partition(".")
    p_area, _, p_action = perm.partition(".")
    if g_area == "*" and perm in EXPLICIT_ONLY:
        return False
    return (g_area == "*" and g_action == p_action) or (g_action == "*" and g_area == p_area)


def granted_permissions(principal: Any) -> set[str]:
    custom = getattr(principal, "permissions", None)
    if custom is not None:
        return set(custom)
    return set(ROLE_PERMISSIONS.get(getattr(principal, "role", ""), set()))


def has_permission(principal: Any, perm: str) -> bool:
    """principal has .role and optionally .permissions (custom role override)."""
    return any(_match(g, perm) for g in granted_permissions(principal))


def is_valid_permission(perm: str) -> bool:
    return perm == "*" or bool(_PERM_RE.match(perm))


def covers(granted: str, requested: str) -> bool:
    """True when `granted` includes everything `requested` grants (both may be patterns).
    Used to stop privilege escalation: nobody hands out a permission they do not hold."""
    if granted == "*":
        return True
    if requested == "*":
        return False
    g_area, _, g_action = granted.partition(".")
    r_area, _, r_action = requested.partition(".")
    if g_area == "*" and requested in EXPLICIT_ONLY:
        return False
    return g_area in ("*", r_area) and g_action in ("*", r_action)


def cannot_grant(principal: Any, perms: list[str]) -> list[str]:
    """The permissions in `perms` the principal may NOT hand out (empty list = all fine)."""
    held = granted_permissions(principal)
    return [p for p in perms if not any(covers(g, p) for g in held)]

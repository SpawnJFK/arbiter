"""Permissions SEAM. Fine-grained checks layered on top of the coarse roles in api/deps.py.

Permission strings are "<area>.<action>", e.g. "jobs.read", "jobs.write", "billing.manage",
"engines.manage", "vendors.manage", "audit.read". Routes call `has_permission(principal, perm)`
or use `require_permission(perm)` from arbiter.api.deps (added by the platform module).

Until the platform module ships custom roles, the built-in mapping below applies, so
existing behaviour does not change.
"""

from __future__ import annotations

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


def _match(granted: str, perm: str) -> bool:
    if granted in ("*", perm):
        return True
    g_area, _, g_action = granted.partition(".")
    p_area, _, p_action = perm.partition(".")
    return (g_area == "*" and g_action == p_action) or (g_action == "*" and g_area == p_area)


def has_permission(principal: Any, perm: str) -> bool:
    """principal has .role and optionally .permissions (custom role override)."""
    custom = getattr(principal, "permissions", None)
    granted = set(custom) if custom else ROLE_PERMISSIONS.get(getattr(principal, "role", ""), set())
    return any(_match(g, perm) for g in granted)

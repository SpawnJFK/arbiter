"""Entitlements: which modules an org may use, written to org.settings["modules"] (D-072).

arbiter.platform.modules stays the only READER (org_has_module / require_module). This module
is the only WRITER: it recomputes the list whenever a subscription changes or the platform
admin changes overrides.

    base  = modules of the plan of the current subscription (status active, trialing or
            past_due; past_due keeps access while the provider retries the payment)
          = []  when the org had a subscription but none is current (lapsed or canceled)
          = everything (DEFAULT_MODULES) when the org never had a subscription: existing
            orgs keep working until they buy a plan (legacy behaviour, D-072)
    final = (base + overrides.add - overrides.remove) + the dependencies of what is left;
            a module whose dependency was explicitly removed is dropped too

Overrides live in org.settings["billing"]["module_overrides"] = {"add": [...], "remove": [...]}.
An org that never had a subscription and has no overrides is left untouched.

Add-ons (platform.modules.ADDONS: eu_processing, byok, custom_models) follow the same rules
(D-077) and are written to org.settings["addons"]: the plan's `addons`, plus
org.settings["billing"]["addon_overrides"]; a legacy org keeps every add-on (no key).
The platform admin's module editor (PUT /admin/orgs/{id}/modules) goes through
`set_exact_modules`, so this module stays the only writer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import Organization, Plan, Subscription
from arbiter.platform.modules import ADDONS, DEFAULT_MODULES, MODULES

ACTIVE_STATUSES = ("active", "trialing", "past_due")


def current_subscription(session: Session, org_id: str) -> Subscription | None:
    """The subscription that grants access now: the most recently updated active one."""
    return session.execute(
        select(Subscription)
        .where(Subscription.org_id == org_id, Subscription.status.in_(ACTIVE_STATUSES))
        .order_by(Subscription.updated_at.desc(), Subscription.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_subscription(session: Session, org_id: str) -> Subscription | None:
    return session.execute(
        select(Subscription)
        .where(Subscription.org_id == org_id)
        .order_by(Subscription.updated_at.desc(), Subscription.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def overrides(org: Organization) -> dict[str, list[str]]:
    raw = ((org.settings or {}).get("billing") or {}).get("module_overrides") or {}
    return {
        "add": [m for m in raw.get("add") or [] if m in MODULES],
        "remove": [m for m in raw.get("remove") or [] if m in MODULES],
    }


def addon_overrides(org: Organization) -> dict[str, list[str]]:
    raw = ((org.settings or {}).get("billing") or {}).get("addon_overrides") or {}
    return {
        "add": [a for a in raw.get("add") or [] if a in ADDONS],
        "remove": [a for a in raw.get("remove") or [] if a in ADDONS],
    }


def set_addon_overrides(org: Organization, add: list[str] | None, remove: list[str] | None) -> None:
    from arbiter.errors import Invalid

    cur = addon_overrides(org)
    new = {
        "add": cur["add"] if add is None else list(dict.fromkeys(add)),
        "remove": cur["remove"] if remove is None else list(dict.fromkeys(remove)),
    }
    bad = [a for a in new["add"] + new["remove"] if a not in ADDONS]
    if bad:
        raise Invalid(f"unknown add-on(s): {', '.join(bad)}", {"allowed": list(ADDONS)})
    settings = dict(org.settings or {})
    billing = dict(settings.get("billing") or {})
    billing["addon_overrides"] = new
    settings["billing"] = billing
    org.settings = settings


def set_overrides(org: Organization, add: list[str] | None, remove: list[str] | None) -> None:
    from arbiter.errors import Invalid

    cur = overrides(org)
    new = {"add": cur["add"] if add is None else list(dict.fromkeys(add)), "remove": cur["remove"]}
    if remove is not None:
        new["remove"] = list(dict.fromkeys(remove))
    bad = [m for m in new["add"] + new["remove"] if m not in MODULES]
    if bad:
        raise Invalid(f"unknown module(s): {', '.join(bad)}", {"allowed": list(MODULES)})
    settings = dict(org.settings or {})
    billing = dict(settings.get("billing") or {})
    billing["module_overrides"] = new
    settings["billing"] = billing
    org.settings = settings


def compute(session: Session, org: Organization) -> tuple[list[str] | None, dict[str, Any]]:
    """(modules, source). modules None = leave org.settings untouched (legacy org)."""
    ov = overrides(org)
    sub = current_subscription(session, org.id)
    source: dict[str, Any] = {"subscription_id": None, "plan": None, "overrides": ov}
    if sub is not None:
        plan = session.execute(select(Plan).where(Plan.key == sub.plan_key)).scalar_one_or_none()
        base = list(plan.modules or []) if plan is not None else []
        source.update({"subscription_id": sub.id, "plan": sub.plan_key, "status": sub.status})
    elif latest_subscription(session, org.id) is not None:
        base = []
        source["status"] = "lapsed"
    elif ov["add"] or ov["remove"]:
        base = list(DEFAULT_MODULES)
        source["status"] = "legacy"
    else:
        return None, {**source, "status": "legacy"}
    mods = [m for m in dict.fromkeys(base + ov["add"]) if m not in ov["remove"]]
    for m in list(mods):
        deps = MODULES[m]["depends_on"]
        if any(dep in ov["remove"] for dep in deps):
            mods.remove(m)  # an explicitly removed dependency takes its dependents with it
            continue
        mods.extend(dep for dep in deps if dep not in mods)
    return [m for m in MODULES if m in mods], source


def compute_addons(session: Session, org: Organization) -> list[str] | None:
    """Add-ons for the org. None = leave org.settings untouched (legacy org: every add-on)."""
    ov = addon_overrides(org)
    sub = current_subscription(session, org.id)
    if sub is not None:
        plan = session.execute(select(Plan).where(Plan.key == sub.plan_key)).scalar_one_or_none()
        base = list(plan.addons or []) if plan is not None else []
    elif latest_subscription(session, org.id) is not None:
        base = []
    elif ov["add"] or ov["remove"]:
        base = list(ADDONS)
    else:
        return None
    chosen = [a for a in dict.fromkeys(base + ov["add"]) if a not in ov["remove"]]
    return [a for a in ADDONS if a in chosen]


def set_exact_modules(session: Session, org: Organization, modules: list[str]) -> list[str]:
    """Platform admin sets the exact module list: stored as overrides against the plan (or the
    legacy default), then refreshed, so a later subscription change keeps the admin's intent."""
    settings = dict(org.settings or {})
    billing = dict(settings.get("billing") or {})
    billing["module_overrides"] = {"add": [], "remove": []}
    settings["billing"] = billing
    org.settings = settings
    base, _ = compute(session, org)
    if base is None:
        base = list(DEFAULT_MODULES)
    wanted = [m for m in MODULES if m in set(modules)]
    set_overrides(org, [m for m in wanted if m not in base], [m for m in base if m not in wanted])
    mods = refresh(session, org)
    if mods is None:  # legacy org and the admin chose every module: no stored list = all
        settings = {k: v for k, v in (org.settings or {}).items() if k != "modules"}
        org.settings = settings
        session.flush()
        return list(DEFAULT_MODULES)
    return mods


def refresh(session: Session, org: Organization) -> list[str] | None:
    """Recompute and write org.settings["modules"] and ["addons"]. Returns the module list
    written (None = modules untouched)."""
    addons = compute_addons(session, org)
    if addons is not None:
        settings = dict(org.settings or {})
        settings["addons"] = addons
        org.settings = settings
    mods, source = compute(session, org)
    if mods is None:
        session.flush()
        return None
    settings = dict(org.settings or {})
    settings["modules"] = mods
    billing = dict(settings.get("billing") or {})
    billing["entitlements_source"] = {k: v for k, v in source.items() if k != "overrides"}
    settings["billing"] = billing
    org.settings = settings
    session.flush()
    return mods

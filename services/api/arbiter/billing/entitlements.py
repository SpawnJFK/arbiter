"""Entitlements: which modules an org may use, written to org.settings["modules"] (D-051).

arbiter.platform.modules stays the only READER (org_has_module / require_module). This module
is the only WRITER: it recomputes the list whenever a subscription changes or the platform
admin changes overrides.

    base  = modules of the plan of the current subscription (status active, trialing or
            past_due; past_due keeps access while the provider retries the payment)
          = []  when the org had a subscription but none is current (lapsed or canceled)
          = everything (DEFAULT_MODULES) when the org never had a subscription: existing
            orgs keep working until they buy a plan (legacy behaviour, D-051)
    final = (base + overrides.add - overrides.remove) + the dependencies of what is left;
            a module whose dependency was explicitly removed is dropped too

Overrides live in org.settings["billing"]["module_overrides"] = {"add": [...], "remove": [...]}.
An org that never had a subscription and has no overrides is left untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import Organization, Plan, Subscription
from arbiter.platform.modules import DEFAULT_MODULES, MODULES

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


def refresh(session: Session, org: Organization) -> list[str] | None:
    """Recompute and write org.settings["modules"]. Returns the list written (None = untouched)."""
    mods, source = compute(session, org)
    if mods is None:
        return None
    settings = dict(org.settings or {})
    settings["modules"] = mods
    billing = dict(settings.get("billing") or {})
    billing["entitlements_source"] = {k: v for k, v in source.items() if k != "overrides"}
    settings["billing"] = billing
    org.settings = settings
    session.flush()
    return mods

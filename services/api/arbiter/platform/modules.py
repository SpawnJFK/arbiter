"""Product modules (editions). The SEAM every feature plugs into.

Arbiter is sold as separable modules on one platform, so a customer can buy one, several
or all of them, and a module can be switched off without breaking the others:

    tms        Web translation: projects, files, jobs, client portal, editor, TM, glossary
    engine     Translation engine API: MT/LLM routing, engines admin, BYOK, own models
    ai         AI quality layer: QE judge, senate, AI review/editor, EU processing route
    pm         Project management (Agency OS): CRM, price lists, workflows, vendors,
               dashboards, AI PM copilot
    auditor    Standalone QA / LQA of bilingual files from any tool, scorecards
    strings    Software string localization: keys, releases, OTA bundles, CLI sync
    community  Reviewer marketplace access (vetted reviewers, payouts)

Rules:
- Every route, worker step and UI section that belongs to a module checks it with
  `org_has_module()` / the `require_module()` dependency. A disabled module returns 404
  with error code `module_disabled` (the feature does not exist for that org).
- Modules never import each other's internals; they talk through contracts.py and the
  pipeline hooks. Removing a module's package must not break import of the others
  (tests/platform/test_module_isolation.py checks the imports statically; MODULE_PACKAGES
  there maps packages to modules).
- Entitlements live in org.settings["modules"] (list of module keys). Billing writes them
  (plan purchase); the platform admin can override. Default for a new org: DEFAULT_MODULES.
"""

from __future__ import annotations

from typing import Any

MODULES: dict[str, dict[str, Any]] = {
    "tms": {"name": "Web translation", "depends_on": []},
    "engine": {"name": "Translation engine API", "depends_on": []},
    "ai": {"name": "AI quality layer", "depends_on": []},
    "pm": {"name": "Project management", "depends_on": []},
    "auditor": {"name": "Quality auditor", "depends_on": []},
    "strings": {"name": "Software strings", "depends_on": ["tms"]},
    "community": {"name": "Reviewer marketplace", "depends_on": ["tms"]},
}

# Everything on by default until billing sells modules separately (keeps current behaviour).
DEFAULT_MODULES: tuple[str, ...] = tuple(MODULES)


def org_modules(org: Any) -> set[str]:
    """Modules enabled for an organization (unknown keys ignored)."""
    settings = getattr(org, "settings", None) or {}
    enabled = settings.get("modules")
    if enabled is None:
        return set(DEFAULT_MODULES)
    return {m for m in enabled if m in MODULES}


def org_has_module(org: Any, module: str) -> bool:
    if module not in MODULES:
        raise ValueError(f"unknown module {module!r}")
    if org is None:  # platform admin and reviewer contexts are not module-gated
        return True
    enabled = org_modules(org)
    return module in enabled and all(dep in enabled for dep in MODULES[module]["depends_on"])


def effective_modules(org: Any) -> list[str]:
    """Modules that actually work for the org (enabled and every dependency enabled)."""
    return [m for m in MODULES if org_has_module(org, m)]


def catalog(org: Any) -> list[dict[str, Any]]:
    effective = set(effective_modules(org))
    return [
        {"key": k, "name": v["name"], "depends_on": list(v["depends_on"]), "enabled": k in effective}
        for k, v in MODULES.items()
    ]


def module_problems(modules: list[str]) -> list[str]:
    """Why a module list cannot be stored (unknown keys, missing dependencies). Empty = fine."""
    problems = [f"unknown module {m!r}" for m in modules if m not in MODULES]
    chosen = set(modules)
    for m in modules:
        for dep in MODULES.get(m, {}).get("depends_on", []):
            if dep not in chosen:
                problems.append(f"module {m!r} needs {dep!r}")
    return problems


def set_org_modules(org: Any, modules: list[str]) -> list[str]:
    """Store the entitlement list (caller validated it). Returns the stored list in catalog order.
    The settings dict is replaced, not mutated, so SQLAlchemy sees the JSON change."""
    ordered = [m for m in MODULES if m in set(modules)]
    org.settings = {**(org.settings or {}), "modules": ordered}
    return ordered


# Paid add-ons on top of modules. Same storage pattern: org.settings["addons"]; None means
# every add-on (orgs that never had a subscription). billing.entitlements writes the list from
# the plan's `addons` plus admin overrides (D-077).
ADDONS: dict[str, dict[str, Any]] = {
    "eu_processing": {"name": "EU processing route", "module": "engine"},
    "byok": {"name": "Bring your own engine keys", "module": "engine"},
    "custom_models": {"name": "Own models (fine-tuned per client)", "module": "engine"},
}


def org_has_addon(org: Any, addon: str) -> bool:
    if addon not in ADDONS:
        raise ValueError(f"unknown add-on {addon!r}")
    if org is None:
        return True
    settings = getattr(org, "settings", None) or {}
    enabled = settings.get("addons")
    if enabled is not None and addon not in enabled:
        return False
    return org_has_module(org, ADDONS[addon]["module"])


def addon_catalog(org: Any) -> list[dict[str, Any]]:
    """Add-ons with their state for the org (read-only in the org UI; billing writes them)."""
    return [
        {"key": k, "name": v["name"], "module": v["module"], "enabled": org_has_addon(org, k)}
        for k, v in ADDONS.items()
    ]

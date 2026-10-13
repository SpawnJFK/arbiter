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
  (enforced by tests/platform/test_module_isolation.py once modules land).
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

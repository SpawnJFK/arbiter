"""Organization settings update shared by PATCH /org and the assistant's update_org action."""

from __future__ import annotations

from typing import Any

from arbiter.errors import Invalid
from arbiter.models import Organization

ORG_FIELDS = (
    "name",
    "default_tier",
    "no_reviewer_policy",
    "ai_subprocessors_opt_in",
    "regulated",
    "vertical",
    "data_retention_days",
)
# Keys kept in org.settings (JSON) rather than columns.
SETTINGS_FIELDS = ("processing_region", "training_consent")


def update_org(org: Organization, data: dict[str, Any]) -> Organization:
    """Apply validated fields. R-SEG-12: a regulated org cannot default to a tier without a
    human reviewer and must wait for a human when none is available."""
    extra = {k: v for k, v in data.items() if k in SETTINGS_FIELDS and v is not None}
    data = {k: v for k, v in data.items() if k in ORG_FIELDS and v is not None}
    if extra.get("processing_region") not in (None, "global", "eu"):
        raise Invalid("processing_region must be global or eu")
    if extra.get("processing_region") == "eu":
        from arbiter.platform.modules import org_has_addon

        # D-052: sold as an add-on. Regulated organizations may use it like any other.
        if not org_has_addon(org, "eu_processing"):
            raise Invalid("the EU processing add-on is not enabled for this organization")
    regulated = data.get("regulated", org.regulated)
    tier = data.get("default_tier", org.default_tier)
    if regulated and tier in ("auto", "ai_review"):
        if "default_tier" in data:
            raise Invalid("regulated organizations cannot use the auto or ai_review tier")
        data["default_tier"] = "hybrid"
    if regulated and data.get("no_reviewer_policy", org.no_reviewer_policy) != "wait":
        if "no_reviewer_policy" in data:
            raise Invalid("regulated organizations must wait for a human reviewer")
        data["no_reviewer_policy"] = "wait"
    for k, v in data.items():
        setattr(org, k, v)
    if extra:
        org.settings = {**(org.settings or {}), **extra}  # new dict: JSON change detection
    return org

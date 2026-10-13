"""Routing failures that must stop a job visibly instead of falling back silently."""

from __future__ import annotations

from arbiter.contracts import EngineError


class RoutingBlocked(EngineError):
    """No engine may be used for this call. Never retried blindly by the pipeline."""

    code = "routing_blocked"


class NoEngineInRegion(RoutingBlocked):
    """processing_region "eu" and no EU engine is configured (D-057). Never falls back."""

    code = "no_eu_engine"

    def __init__(self, purpose: str, region: str = "eu") -> None:
        super().__init__(
            f"no EU engine configured for {purpose}" if region == "eu" else f"no {region} engine"
        )
        self.purpose = purpose
        self.region = region


class BudgetExceeded(RoutingBlocked):
    """The org's monthly cost cap for a provider is reached (engine_budgets)."""

    code = "budget_exceeded"

    def __init__(self, providers: list[str]) -> None:
        super().__init__(f"budget exceeded: monthly cap reached for {', '.join(sorted(set(providers)))}")
        self.providers = sorted(set(providers))

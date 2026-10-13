"""Payment provider adapters and the registry that picks one (D-072).

provider_for(name, session)   a specific adapter (paddle | stripe | manual)
default_provider(session, org)
    1. org.settings["billing"]["provider"] (admin override, e.g. "manual" for an
       enterprise contract with bank transfer)
    2. ARBITER_BILLING_PROVIDER when it is paddle/stripe/manual
    3. auto: paddle when configured, else manual
    A chosen provider that is not configured falls back to manual, so checkout never
    sends a customer to a provider without keys.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from arbiter.billing.providers.base import BillingProvider, ProviderNotConfigured
from arbiter.config import get_settings

PROVIDERS = ("paddle", "stripe", "manual")


def provider_for(name: str, session: Session | None = None) -> BillingProvider:
    if name == "paddle":
        from arbiter.billing.providers.paddle import PaddleProvider

        return PaddleProvider()
    if name == "stripe":
        from arbiter.billing.providers.stripe import StripeProvider

        return StripeProvider()
    if name in ("manual", "admin", "internal"):
        if session is None:
            raise ValueError("the manual provider needs a database session")
        from arbiter.billing.providers.manual import ManualProvider

        return ManualProvider(session)
    raise ProviderNotConfigured(f"unknown payment provider {name!r}")


def default_provider(session: Session, org: Any | None = None) -> BillingProvider:
    wanted = None
    if org is not None:
        wanted = ((org.settings or {}).get("billing") or {}).get("provider")
    if wanted not in PROVIDERS:
        wanted = get_settings().billing_provider
    if wanted == "auto":
        wanted = "paddle"
    p = provider_for(wanted, session)
    if not p.configured():
        return provider_for("manual", session)
    return p


def provider_status() -> dict[str, dict[str, Any]]:
    """For the admin page: which adapters are configured (never shows keys)."""
    from arbiter.billing.providers.paddle import PaddleProvider
    from arbiter.billing.providers.stripe import StripeProvider

    s = get_settings()
    return {
        "paddle": {"configured": PaddleProvider().configured(), "environment": s.paddle_environment},
        "stripe": {"configured": StripeProvider().configured(), "enabled": s.billing_provider == "stripe"},
        "manual": {"configured": True},
        "selected": {"setting": s.billing_provider},
    }

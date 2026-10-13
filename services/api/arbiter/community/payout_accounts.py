"""Payee payout accounts: method setup, onboarding status, minimum payout per method (D-052).

A payee (reviewer now; Agency OS vendors use the same table with payee_kind "vendor") picks a
method and gives its details. The chosen method becomes ReviewerProfile.payout_method /
payout_details, which community.payouts reads when it pays.

    method    onboarding                                  status after setup
    payoneer  Payoneer registration link (hosted)         pending -> active via refresh
    paypal    PayPal email                                active
    sepa      IBAN (mod-97 checked), BIC optional, holder active
    wise      Wise email or IBAN, holder                  active

Minimum payout per method (STARTING VALUES, they cover rail fees; override with
ARBITER_PAYOUT_MINIMUMS='{"paypal": "10"}'): the effective threshold of a payee is
max(profile.payout_threshold, method minimum). SEPA batches cost us nothing per item, so 0.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.billing.ledger import money
from arbiter.community.payout_rails import METHODS
from arbiter.community.payout_rails.bank import validate_details
from arbiter.config import get_settings
from arbiter.errors import Invalid, NotFound
from arbiter.models import PayoutAccount, ReviewerProfile, utcnow

DEFAULT_MINIMUMS: dict[str, Decimal] = {
    "payoneer": Decimal("20.00"),
    "paypal": Decimal("5.00"),
    "sepa": Decimal("0.00"),
    "wise": Decimal("5.00"),
}
ONBOARDING = {"payoneer": True, "paypal": False, "sepa": False, "wise": False}
FIELDS: dict[str, list[str]] = {
    "payoneer": [],
    "paypal": ["email"],
    "sepa": ["account_holder", "iban", "bic"],
    "wise": ["account_holder", "email", "iban"],
}


def minimums() -> dict[str, Decimal]:
    out = dict(DEFAULT_MINIMUMS)
    raw = get_settings().payout_minimums.strip()
    if raw:
        try:
            for k, v in json.loads(raw).items():
                if k in out:
                    out[k] = Decimal(str(v))
        except (ValueError, InvalidOperation, AttributeError):
            raise ValueError("ARBITER_PAYOUT_MINIMUMS must be a JSON object of method -> amount") from None
    return out


def method_minimum(method: str) -> Decimal:
    return minimums().get(method, Decimal("0"))


def effective_threshold(profile: ReviewerProfile) -> Decimal:
    return max(Decimal(profile.payout_threshold or 0), method_minimum(profile.payout_method))


def get_account(session: Session, payee_kind: str, payee_id: str, method: str) -> PayoutAccount | None:
    return session.execute(
        select(PayoutAccount).where(
            PayoutAccount.payee_kind == payee_kind,
            PayoutAccount.payee_id == payee_id,
            PayoutAccount.method == method,
        )
    ).scalar_one_or_none()


def account_ready(session: Session, profile: ReviewerProfile) -> tuple[bool, str | None]:
    """Methods with onboarding need an active account. Others are checked by the rail at send."""
    if ONBOARDING.get(profile.payout_method):
        acct = get_account(session, "reviewer", profile.id, profile.payout_method)
        if acct is None or acct.status != "active":
            return False, f"{profile.payout_method} onboarding not finished"
    return True, None


def _validate(method: str, details: dict[str, Any]) -> dict[str, str]:
    if method == "paypal":
        email = str(details.get("email") or "").strip()
        if "@" not in email or len(email) > 320:
            raise Invalid("a valid PayPal email is required")
        return {"email": email}
    if method in ("sepa", "wise"):
        try:
            return validate_details(method, details)
        except ValueError as e:
            raise Invalid(str(e)) from None
    return {}


def account_view(acct: PayoutAccount | None, method: str) -> dict[str, Any]:
    details = dict(acct.details or {}) if acct else {}
    if "iban" in details:  # never echo a full account number
        details["iban"] = f"{details['iban'][:4]}...{details['iban'][-4:]}"
    return {
        "method": method,
        "status": acct.status if acct else "not_set_up",
        "onboarding_required": ONBOARDING[method],
        "onboarding_url": acct.onboarding_url if acct and acct.status == "pending" else None,
        "details": details,
        "fields": FIELDS[method],
        "minimum_payout": money(method_minimum(method)),
        "updated_at": acct.updated_at.isoformat() if acct and acct.updated_at else None,
    }


def methods_view(session: Session, profile: ReviewerProfile) -> dict[str, Any]:
    from arbiter.community.payout_rails import RailRouter

    configured = set(RailRouter().configured_methods())
    items = []
    for m in METHODS:
        v = account_view(get_account(session, "reviewer", profile.id, m), m)
        v["available"] = m in configured
        v["selected"] = profile.payout_method == m
        items.append(v)
    return {
        "selected": profile.payout_method or None,
        "effective_threshold": money(effective_threshold(profile)) if profile.payout_method else None,
        "items": items,
    }


def setup(
    session: Session,
    profile: ReviewerProfile,
    method: str,
    details: dict[str, Any],
    *,
    rails: Any | None = None,
) -> dict[str, Any]:
    """POST /reviewer/payout-accounts: save the method, start onboarding where needed."""
    if method not in METHODS:
        raise Invalid(f"method must be one of {', '.join(METHODS)}")
    clean = _validate(method, details or {})
    acct = get_account(session, "reviewer", profile.id, method)
    if acct is None:
        acct = PayoutAccount(payee_kind="reviewer", payee_id=profile.id, method=method, details={})
        session.add(acct)
    if method == "payoneer":
        from arbiter.community.payout_rails import RailRouter

        rail = (rails or RailRouter()).rail("payoneer")
        if rail is None or not rail.configured():
            raise Invalid("Payoneer payouts are not available yet; choose another method")
        try:
            link = rail.registration_link(
                profile.id, f"{get_settings().web_base_url.rstrip('/')}/reviewer/payouts"
            )
        except RuntimeError as e:
            raise Invalid(f"could not start Payoneer onboarding: {e}") from None
        acct.provider_payee_id = profile.id
        acct.onboarding_url = link
        if acct.status != "active":
            acct.status = "pending"
        clean = {"payee_id": profile.id}
    else:
        acct.status = "active"
        acct.onboarding_url = None
    acct.details = clean
    acct.updated_at = utcnow()
    profile.payout_method = method
    profile.payout_details = clean
    session.flush()
    return account_view(acct, method)


def refresh(
    session: Session, profile: ReviewerProfile, method: str, *, rails: Any | None = None
) -> dict[str, Any]:
    """Ask the rail for the onboarding status (Payoneer)."""
    acct = get_account(session, "reviewer", profile.id, method)
    if acct is None:
        raise NotFound("payout account not set up")
    if ONBOARDING.get(method):
        from arbiter.community.payout_rails import RailRouter

        rail = (rails or RailRouter()).rail(method)
        if rail is None or not rail.configured():
            raise Invalid(f"{method} payouts are not available")
        try:
            acct.status = rail.payee_status(acct.provider_payee_id or profile.id)
        except RuntimeError as e:
            raise Invalid(str(e)) from None
        acct.updated_at = utcnow()
        session.flush()
    return account_view(acct, method)

"""Plans catalog, credit wallet, entitlements and the platform fee (D-051, D-052, D-053)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from bill_helpers import make_file, make_org

from arbiter.billing import catalog, credits, entitlements, fees, ledger, quotes, usage
from arbiter.errors import Invalid
from arbiter.models import CreditLedgerEntry, LedgerEntry, Subscription, UsageRecord, utcnow
from arbiter.platform.modules import org_has_module


def _ledger_sum(db) -> Decimal:
    return sum((e.amount for e in db.query(LedgerEntry)), Decimal("0"))


def test_seed_is_data_and_idempotent(db):
    first = catalog.seed_starter_catalog(db)
    assert first == {"plans": 4, "packs": 3}
    assert catalog.seed_starter_catalog(db) == {"plans": 0, "packs": 0}
    keys = [p.key for p in catalog.list_plans(db)]
    assert keys == ["starter", "team", "business", "enterprise"]
    team = catalog.get_plan(db, "team")
    assert team.modules == ["tms", "ai", "pm", "community"]
    assert catalog.plan_price(team, "month", "EUR") == Decimal("199.00")
    assert catalog.overage_rate(team, "word", "EUR") == Decimal("0.0120")
    assert catalog.get_plan(db, "enterprise").custom is True
    # Editing is data: the admin changes a price, seeding does not overwrite it.
    catalog.update_plan(db, "team", {"prices": {"month": {"EUR": "189"}}})
    catalog.seed_starter_catalog(db)
    assert catalog.plan_price(catalog.get_plan(db, "team"), "month", "EUR") == Decimal("189.00")


def test_plan_validation(db):
    with pytest.raises(Invalid):
        catalog.create_plan(db, {"key": "x", "name": "X", "modules": ["nope"]})
    with pytest.raises(Invalid):
        catalog.create_plan(db, {"key": "x", "name": "X", "prices": {"month": {"EUR": 9.99}}})  # float
    with pytest.raises(Invalid):
        catalog.create_plan(db, {"key": "Bad Key", "name": "X"})
    p = catalog.create_plan(db, {"key": "loc", "name": "Strings only", "modules": ["strings"]})
    assert p.modules == ["tms", "strings"]  # dependency added


def test_credit_wallet_fifo_expiry_refund_and_ledger(db):
    org = make_org(db)
    a = credits.add_lot(
        db, org.id, Decimal("50.00"), kind="purchase", idempotency_key="k-a", valid_days=30, ref="txn_a"
    )
    b = credits.add_lot(
        db, org.id, Decimal("20.00"), kind="grant", idempotency_key="k-b", valid_days=10, ref="promo"
    )
    assert credits.add_lot(db, org.id, Decimal("50.00"), kind="purchase", idempotency_key="k-a").id == a.id
    assert credits.balance(db, org.id) == Decimal("70.00")

    # Earliest expiry first: the grant (10 days) is spent before the purchase (30 days).
    used = credits.consume(db, org.id, Decimal("25.00"), idempotency_key="ovr-1")
    assert used == Decimal("25.00")
    assert credits.lot_remaining(db, b) == Decimal("0")
    assert credits.lot_remaining(db, a) == Decimal("45.00")
    assert credits.consume(db, org.id, Decimal("25.00"), idempotency_key="ovr-1") == Decimal(
        "25.00"
    )  # replay
    assert credits.balance(db, org.id) == Decimal("45.00")

    # More than the wallet holds: covers what it can.
    assert credits.consume(db, org.id, Decimal("100"), idempotency_key="ovr-2") == Decimal("45.00")
    assert credits.balance(db, org.id) == 0

    c = credits.add_lot(db, org.id, Decimal("10.00"), kind="purchase", idempotency_key="k-c", ref="txn_c")
    assert credits.refund_lot(db, c, Decimal("4.00"), idempotency_key="rf-1") == Decimal("4.00")
    assert credits.refund_lot(db, c, Decimal("4.00"), idempotency_key="rf-1") == Decimal("4.00")  # replay
    assert credits.lot_remaining(db, c) == Decimal("6.00")

    c.expires_at = utcnow() - timedelta(seconds=1)
    db.flush()
    assert credits.expire_lots(db) == 1
    assert credits.expire_lots(db) == 0
    assert credits.balance(db, org.id) == 0
    assert ledger.account_balance(db, ledger.REVENUE_BREAKAGE) == Decimal("6.00")
    assert ledger.account_balance(db, ledger.REVENUE_USAGE) == Decimal("70.00")
    # Wallet rows and the double-entry ledger agree, and the ledger balances.
    wallet = sum((r.amount for r in db.query(CreditLedgerEntry).filter_by(org_id=org.id)), Decimal("0"))
    assert wallet == credits.balance(db, org.id)
    assert _ledger_sum(db) == 0
    view = credits.credits_view(db, org.id)
    assert view["balance"] == "0.00" and view["lots"] == []


def test_entitlements_from_subscription_overrides_and_legacy(db):
    catalog.seed_starter_catalog(db)
    org = make_org(db)
    # Legacy org: never had a subscription, nothing is written, every module stays on.
    assert entitlements.refresh(db, org) is None
    assert org_has_module(org, "engine")

    db.add(
        Subscription(org_id=org.id, plan_key="starter", provider="admin", status="active", seats=2, meta={})
    )
    db.flush()
    assert entitlements.refresh(db, org) == ["tms", "ai"]
    assert not org_has_module(org, "pm")

    entitlements.set_overrides(org, ["strings"], ["ai"])
    assert entitlements.refresh(db, org) == ["tms", "strings"]
    entitlements.set_overrides(org, ["strings", "community"], ["tms"])
    assert entitlements.refresh(db, org) == ["ai"]  # removing tms takes its dependents with it

    entitlements.set_overrides(org, [], [])
    sub = db.query(Subscription).filter_by(org_id=org.id).one()
    sub.status = "canceled"
    db.flush()
    assert entitlements.refresh(db, org) == []  # lapsed: no modules
    assert not org_has_module(org, "tms")


def test_platform_fee_on_quotes_and_review_pay(db):
    org = make_org(db, settings={"billing": {"platform_fee_percent": "8"}})
    assert fees.platform_fee_percent(org) == Decimal("8")
    with pytest.raises(Invalid):
        fees.set_platform_fee_percent(org, "9")
    with pytest.raises(Invalid):
        fees.set_platform_fee_percent(org, "-1")
    fees.set_platform_fee_percent(org, "5")
    assert fees.fee_for(Decimal("10.00"), Decimal("5")) == Decimal("0.50")

    q = quotes.build_quote(db, org, make_file(db, org), ["de"])
    assert "platform_fee" not in q.tiers["auto"] and "platform_fee" not in q.tiers["ai_review"]
    full = q.tiers["full"]
    assert full["platform_fee"]["percent"] == "5"
    expected_basis = (Decimal(q.word_count) * quotes.HUMAN_RATE_ESTIMATE).quantize(Decimal("0.01"))
    assert full["platform_fee"]["basis_estimate"] == str(expected_basis)
    assert Decimal(full["total_estimate"]) == Decimal(full["price"]) + Decimal(
        full["platform_fee"]["estimate"]
    )

    fee = fees.charge_fee(db, org, Decimal("3.00"), ref="tsk_1", job_id="job_1")
    assert fee == Decimal("0.15")
    assert fees.charge_fee(db, org, Decimal("3.00"), ref="tsk_1", job_id="job_1") == Decimal("0.15")  # once
    assert db.query(UsageRecord).filter_by(unit="platform_fee").count() == 1
    assert ledger.account_balance(db, ledger.REVENUE_PLATFORM_FEE) == Decimal("0.15")
    assert usage.usage_view(db, org.id)["platform_fee"] == "0.15"
    assert _ledger_sum(db) == 0

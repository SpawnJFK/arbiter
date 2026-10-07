from __future__ import annotations

from decimal import Decimal

import pytest
from bill_helpers import make_org

from arbiter.billing import invoices, usage
from arbiter.community.errors import Invalid
from arbiter.config import Settings
from arbiter.models import UsageRecord


def test_usage_record_is_idempotent(db):
    org = make_org(db)
    r1 = usage.record(db, org.id, "job_1", "word", 120, Decimal("8.40"), "job_1:words", {"tier": "hybrid"})
    r2 = usage.record(db, org.id, "job_1", "word", 999, Decimal("99"), "job_1:words")
    assert r1.id == r2.id and r2.quantity == Decimal("120")
    assert db.query(UsageRecord).count() == 1
    with pytest.raises(TypeError):
        usage.record(db, org.id, None, "word", 1.5, Decimal("0"), "float")
    with pytest.raises(Invalid):
        usage.record(db, org.id, None, "minutes", 1, Decimal("0"), "bad-unit")


def test_ai_units_and_usage_view(db):
    org = make_org(db)
    assert usage.ai_units("senate", 10) == Decimal("4.00")
    assert usage.ai_units("qe", 3) == Decimal("0.15")
    usage.record(db, org.id, "job_1", "word", 100, Decimal("7.00"), "k1", period="2030-03")
    usage.record(
        db, org.id, "job_1", "ai_unit", usage.ai_units("qe", 100), Decimal("0.50"), "k2", period="2030-03"
    )
    usage.record(db, org.id, "job_1", "review_decision", 4, Decimal("0"), "k3", period="2030-03")
    usage.record(db, org.id, "job_2", "word", 50, Decimal("3.50"), "k4", period="2030-04")
    view = usage.usage_view(db, org.id, "2030-03")
    assert view == {
        "period": "2030-03",
        "words": 100,
        "ai_units": "5.00",
        "review_decisions": 4,
        "storage_gb": "0.00",
        "amount": "7.50",
        "currency": "EUR",
    }


def test_invoice_numbering_idempotency_and_lines(db, monkeypatch):
    monkeypatch.delenv("ARBITER_SELLER_COUNTRY", raising=False)
    monkeypatch.delenv("ARBITER_VAT_RATE", raising=False)
    monkeypatch.setattr("arbiter.billing.invoices.get_settings", lambda: Settings())
    a, b = make_org(db), make_org(db)
    usage.record(db, a.id, "job_1", "word", 100, Decimal("7.004"), "a1", period="2030-05")
    usage.record(db, a.id, "job_1", "word", 50, Decimal("3.50"), "a2", period="2030-05")
    usage.record(db, a.id, "job_2", "ai_unit", Decimal("2.5"), Decimal("1.25"), "a3", period="2030-05")
    usage.record(db, b.id, "job_3", "word", 10, Decimal("0.70"), "b1", period="2030-05")

    inv_a = invoices.build_invoice(db, a.id, "2030-05")
    inv_b = invoices.build_invoice(db, b.id, "2030-05")
    assert inv_a.number == "ARB-203005-0001" and inv_b.number == "ARB-203005-0002"
    assert invoices.build_invoice(db, a.id, "2030-05").id == inv_a.id  # idempotent

    view = invoices.invoice_view(inv_a)
    assert view["lines"] == [
        {"type": "usage", "unit": "ai_unit", "job_id": "job_2", "quantity": "2.5", "amount": "1.25"},
        {"type": "usage", "unit": "word", "job_id": "job_1", "quantity": "150", "amount": "10.50"},
    ]
    assert view["subtotal"] == "11.75" and view["tax"] == "0.00" and view["total"] == "11.75"
    assert "legal and tax review" in view["tax_note"]
    assert [i["number"] for i in invoices.list_invoices(db, a.id)] == ["ARB-203005-0001"]

    with pytest.raises(Invalid):
        invoices.build_invoice(db, a.id, "2030-06")  # no usage
    with pytest.raises(Invalid):
        invoices.build_invoice(db, a.id, "2030-13")


def test_reverse_charge_and_configured_vat(db, monkeypatch):
    monkeypatch.setenv("ARBITER_SELLER_COUNTRY", "RS")
    monkeypatch.setenv("ARBITER_VAT_RATE", "0.20")
    monkeypatch.setattr("arbiter.billing.invoices.get_settings", lambda: Settings())
    eu_b2b = make_org(db, settings={"vat_id": "DE123456789", "country": "DE"})
    domestic = make_org(db, settings={"vat_id": "RS100000000", "country": "RS"})
    for org in (eu_b2b, domestic):
        usage.record(db, org.id, "job", "word", 100, Decimal("10.00"), f"{org.id}:w", period="2030-07")

    rc = invoices.invoice_view(invoices.build_invoice(db, eu_b2b.id, "2030-07"))
    assert rc["tax"] == "0.00" and rc["total"] == "10.00"
    assert rc["tax_note"].startswith("Reverse charge")

    dom = invoices.invoice_view(invoices.build_invoice(db, domestic.id, "2030-07"))
    assert dom["tax"] == "2.00" and dom["total"] == "12.00" and dom["tax_rate"] == "0.20"

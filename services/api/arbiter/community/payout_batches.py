"""Bank transfer batches for the bank rail (D-052): build the file, then confirm payouts.

build_batch collects every payout that was sent through the bank rail (state sent,
provider_ref "bank:...", method sepa or wise) and is not in a batch yet, writes the file to
storage and records a PayoutBatch. settle_batch / complete confirm what the bank executed;
the ledger moves through community.payouts.complete_payout like any provider result.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.billing.ledger import money
from arbiter.community import payouts
from arbiter.community.payout_rails import bank
from arbiter.config import get_settings
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import Payout, PayoutBatch, ReviewerProfile, new_id

FORMAT_FOR = {"pain001": ("sepa",), "csv": ("sepa", "wise"), "wise_csv": ("sepa", "wise")}
MEDIA = {"pain001": ("application/xml", "xml"), "csv": ("text/csv", "csv"), "wise_csv": ("text/csv", "csv")}


def _batched_ids(session: Session) -> set[str]:
    out: set[str] = set()
    for ids in session.execute(select(PayoutBatch.payout_ids)).scalars():
        out.update(ids or [])
    return out


def batch_view(b: PayoutBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "method": b.method,
        "format": b.format,
        "item_count": b.item_count,
        "total": money(b.total),
        "currency": b.currency,
        "payout_ids": list(b.payout_ids or []),
        "download_path": f"/admin/payout-batches/{b.id}/file",
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def build_batch(session: Session, fmt: str) -> dict[str, Any]:
    if fmt not in bank.FORMATS:
        raise Invalid(f"format must be one of {', '.join(bank.FORMATS)}")
    methods = FORMAT_FOR[fmt]
    done = _batched_ids(session)
    rows = [
        p
        for p in session.execute(
            select(Payout)
            .where(Payout.state == "sent", Payout.method.in_(methods), Payout.provider_ref.like("bank:%"))
            .order_by(Payout.created_at)
        ).scalars()
        if p.id not in done
    ]
    if not rows:
        raise Conflict("no bank payouts waiting for a batch")
    items = []
    for p in rows:
        prof = session.get(ReviewerProfile, p.reviewer_id)
        details = dict(prof.payout_details or {}) if prof else {}
        try:
            clean = bank.validate_details(p.method, details)
        except ValueError as e:
            raise Invalid(f"payout {p.id}: {e}") from None
        items.append(
            {
                "end_to_end_id": p.id,
                "name": clean.get("account_holder") or (prof.legal_name if prof else ""),
                "iban": clean.get("iban", ""),
                "bic": clean.get("bic", ""),
                "email": clean.get("email", ""),
                "amount": Decimal(p.amount),
                "currency": p.currency,
                "reference": f"Payout {p.id}",
            }
        )
    batch_id = new_id("pbt")
    if fmt == "pain001":
        if any(i["currency"] != "EUR" for i in items):
            raise Invalid("pain.001 SEPA files are EUR only")
        try:
            data = bank.pain001(batch_id, items)
        except ValueError as e:
            raise Invalid(str(e)) from None
    elif fmt == "csv":
        data = bank.plain_csv(items)
    else:
        data = bank.wise_csv(items, get_settings().currency)
    _, ext = MEDIA[fmt]
    key = storage.make_key("platform", "payout-batches", batch_id, f"{batch_id}.{ext}")
    storage.put(key, data)
    currencies = {i["currency"] for i in items}
    b = PayoutBatch(
        id=batch_id,
        method=methods[0] if len(methods) == 1 else "mixed",
        format=fmt,
        payout_ids=[p.id for p in rows],
        item_count=len(rows),
        total=sum((i["amount"] for i in items), Decimal("0")),
        currency=currencies.pop() if len(currencies) == 1 else "XXX",
        storage_key=key,
    )
    session.add(b)
    session.flush()
    return batch_view(b)


def batch_file(session: Session, batch_id: str) -> tuple[bytes, str, str]:
    b = session.get(PayoutBatch, batch_id)
    if b is None:
        raise NotFound("batch not found")
    media, ext = MEDIA[b.format]
    return storage.get(b.storage_key), media, f"{b.id}.{ext}"


def complete(session: Session, payout_id: str, *, ok: bool, reason: str | None = None) -> dict[str, Any]:
    p = session.get(Payout, payout_id)
    if p is None:
        raise NotFound("payout not found")
    if p.state != "sent":
        raise Conflict(f"payout is {p.state}, not sent")
    payouts.complete_payout(session, p, ok=ok, reason=reason)
    return payouts.payout_view(p)


def settle_batch(session: Session, batch_id: str) -> dict[str, Any]:
    b = session.get(PayoutBatch, batch_id)
    if b is None:
        raise NotFound("batch not found")
    settled = 0
    for pid in b.payout_ids or []:
        p = session.get(Payout, pid)
        if p is not None and p.state == "sent":
            payouts.complete_payout(session, p, ok=True)
            settled += 1
    return {"batch": batch_view(b), "settled": settled}

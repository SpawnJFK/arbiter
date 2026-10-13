"""Agency vendors (module pm): the agency's own translators, reviewers and partner agencies.

Separate from the platform reviewer marketplace (arbiter.community): a vendor belongs to one
org, is offered work by that org's PMs and is paid by that org (purchase orders, vendor
invoices in arbiter.agency.procurement), never through the platform ledger.

Rate lookup for (source_lang, target_lang, service, unit), most specific first (like price
lists, arbiter.agency.pricelists):
  1. exact pair    rate with source_lang and target_lang both matching
  2. target only   rate with target_lang matching and no source_lang
  3. any pair      rate with neither language
A rate with unit "minimum" is the minimum charge per assignment for that service.

CSV import columns (header row, case-insensitive; unknown columns ignored):
  name (required), kind, email, phone, country, status, pairs ("en>de;en>fr", services from
  the `services` column for every pair, default translation+review), services ("translation|review"),
  domains ("legal|pharma"), rate_per_word, currency, capacity_words_per_day, rating, tax_id,
  iban, notes, nda_signed (yes/no/true/false/1/0)
A row whose email (or name, without email) matches an existing vendor updates it.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.agency.common import currency, iso, lang
from arbiter.agency.vendor_schemas import (
    SERVICES,
    AbsenceIn,
    DocumentIn,
    PairIn,
    VendorIn,
    VendorPatch,
    VendorRateIn,
)
from arbiter.errors import Invalid, NotFound
from arbiter.models import NumberSeries, Vendor, VendorAbsence, VendorDocument, new_id, utcnow

log = logging.getLogger(__name__)
CSV_MAX_ROWS = 5000


# --------------------------------------------------------------------------- lookups


def get_vendor(session: Session, org_id: str, vendor_id: str, *, lock: bool = False) -> Vendor:
    q = select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id)
    if lock:
        q = q.with_for_update()
    v = session.execute(q).scalar_one_or_none()
    if v is None:
        raise NotFound("vendor not found")
    return v


def find_vendor(session: Session, org_id: str, *, email: str | None, name: str) -> Vendor | None:
    if email:
        v = (
            session.execute(
                select(Vendor).where(Vendor.org_id == org_id, func.lower(Vendor.email) == email.lower())
            )
            .scalars()
            .first()
        )
        if v is not None:
            return v
    return (
        session.execute(
            select(Vendor).where(Vendor.org_id == org_id, func.lower(Vendor.name) == name.strip().lower())
        )
        .scalars()
        .first()
    )


# --------------------------------------------------------------------------- normalisation


def _pairs(pairs: list[PairIn]) -> list[dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for p in pairs:
        s, t = lang(p.source_lang), lang(p.target_lang)
        assert s and t
        if s == t:
            raise Invalid("a language pair needs two different languages", {"pair": f"{s}>{t}"})
        cur = out.setdefault((s, t), {"source_lang": s, "target_lang": t, "services": []})
        cur["services"] = sorted(set(cur["services"]) | set(p.services), key=SERVICES.index)
    return list(out.values())


def _rates(rates: list[VendorRateIn], default_currency: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for r in rates:
        key = (lang(r.source_lang), lang(r.target_lang), r.service, r.unit)
        if key in seen:
            raise Invalid(
                "duplicate vendor rate for the same languages, service and unit",
                {"source_lang": key[0], "target_lang": key[1], "service": key[2], "unit": key[3]},
            )
        seen.add(key)
        out.append(
            {
                "source_lang": key[0],
                "target_lang": key[1],
                "service": r.service,
                "unit": r.unit,
                "rate": str(r.rate.normalize()),
                "currency": currency(r.currency, default_currency),
            }
        )
    return out


def _domains(domains: list[str]) -> list[str]:
    return sorted({d.strip().lower() for d in domains if d and d.strip()})


# --------------------------------------------------------------------------- CRUD


def create_vendor(session: Session, org_id: str, body: VendorIn) -> Vendor:
    cur = currency(body.currency)
    v = Vendor(
        org_id=org_id,
        kind=body.kind,
        name=body.name,
        email=str(body.email).lower() if body.email else None,
        phone=body.phone,
        country=body.country.upper() if body.country else None,
        status=body.status,
        pairs=_pairs(body.pairs),
        domains=_domains(body.domains),
        rates=_rates(body.rates, cur),
        currency=cur,
        rating=body.rating,
        notes=body.notes,
        legal_name=body.legal_name,
        tax_id=body.tax_id,
        address=body.address,
        payment_method=body.payment_method,
        iban=body.iban,
        swift=body.swift,
        payment_terms_days=body.payment_terms_days,
        capacity_words_per_day=body.capacity_words_per_day,
        working_days=list(body.working_days),
        timezone=body.timezone,
        nda_signed=body.nda_signed,
        nda_signed_at=body.nda_signed_at,
    )
    session.add(v)
    session.flush()
    return v


def update_vendor(session: Session, v: Vendor, body: VendorPatch) -> Vendor:
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise Invalid("name cannot be empty")
    if "currency" in data and data["currency"] is not None:
        v.currency = currency(data.pop("currency"))
    for key in ("pairs", "rates", "domains"):
        if key in data and data[key] is None:
            raise Invalid(f"{key} cannot be null")
    if "pairs" in data:
        v.pairs = _pairs(body.pairs or [])
        data.pop("pairs")
    if "rates" in data:
        v.rates = _rates(body.rates or [], v.currency)
        data.pop("rates")
    if "domains" in data:
        v.domains = _domains(data.pop("domains"))
    if "email" in data:
        v.email = str(data.pop("email")).lower() if data.get("email") else None
        data.pop("email", None)
    if "country" in data:
        v.country = data.pop("country").upper() if data.get("country") else None
        data.pop("country", None)
    for key, value in data.items():
        if key in ("status", "kind") and value is None:
            continue
        setattr(v, key, value)
    v.updated_at = utcnow()
    session.flush()
    return v


def vendor_view(v: Vendor, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": v.id,
        "kind": v.kind,
        "name": v.name,
        "email": v.email,
        "phone": v.phone,
        "country": v.country,
        "status": v.status,
        "pairs": [dict(p) for p in v.pairs or []],
        "domains": list(v.domains or []),
        "rates": [dict(r) for r in v.rates or []],
        "currency": v.currency,
        "rating": str(Decimal(v.rating).quantize(Decimal("0.01"))) if v.rating is not None else None,
        "notes": v.notes,
        "legal_name": v.legal_name,
        "tax_id": v.tax_id,
        "address": v.address,
        "payment_method": v.payment_method,
        "iban": v.iban,
        "swift": v.swift,
        "payment_terms_days": v.payment_terms_days,
        "capacity_words_per_day": v.capacity_words_per_day,
        "working_days": list(v.working_days or []),
        "timezone": v.timezone,
        "nda_signed": v.nda_signed,
        "nda_signed_at": iso(v.nda_signed_at),
        "created_at": iso(v.created_at),
        "updated_at": iso(v.updated_at),
    }
    if extra:
        out.update(extra)
    return out


# --------------------------------------------------------------------------- availability & documents


def add_absence(session: Session, v: Vendor, body: AbsenceIn) -> VendorAbsence:
    a = VendorAbsence(
        org_id=v.org_id, vendor_id=v.id, start_date=body.start_date, end_date=body.end_date, note=body.note
    )
    session.add(a)
    session.flush()
    return a


def absence_view(a: VendorAbsence) -> dict[str, Any]:
    return {
        "id": a.id,
        "vendor_id": a.vendor_id,
        "start_date": iso(a.start_date),
        "end_date": iso(a.end_date),
        "note": a.note,
        "created_at": iso(a.created_at),
    }


def add_document(session: Session, v: Vendor, body: DocumentIn) -> VendorDocument:
    d = VendorDocument(
        org_id=v.org_id,
        vendor_id=v.id,
        kind=body.kind,
        title=body.title,
        signed=body.signed,
        signed_at=body.signed_at,
        valid_until=body.valid_until,
    )
    session.add(d)
    if body.kind == "nda" and body.signed:
        v.nda_signed = True
        v.nda_signed_at = body.signed_at or utcnow().date()
    session.flush()
    return d


def document_view(d: VendorDocument) -> dict[str, Any]:
    return {
        "id": d.id,
        "vendor_id": d.vendor_id,
        "kind": d.kind,
        "title": d.title,
        "signed": d.signed,
        "signed_at": iso(d.signed_at),
        "valid_until": iso(d.valid_until),
        "filename": d.filename,
        "created_at": iso(d.created_at),
    }


# --------------------------------------------------------------------------- pairs & rates


def _covers(have: str | None, want: str | None) -> bool:
    """Language match exactly or by primary subtag (pair "sr" serves "sr-latn" and back)."""
    if not want or not have:
        return True
    h, w = have.lower(), want.lower()
    return h == w or w.startswith(h + "-") or h.startswith(w + "-")


def serves(v: Vendor, source_lang: str, target_lang: str, service: str | None = None) -> bool:
    for p in v.pairs or []:
        if (
            _covers(p.get("source_lang"), source_lang)
            and _covers(p.get("target_lang"), target_lang)
            and (service is None or service in (p.get("services") or []))
        ):
            return True
    return False


def rate_for(
    v: Vendor, source_lang: str, target_lang: str, service: str, unit: str = "word"
) -> tuple[Decimal, str] | None:
    """(rate, currency) of the most specific matching rate, or None."""
    s, t = lang(source_lang), lang(target_lang)
    best: tuple[int, dict[str, Any]] | None = None
    for r in v.rates or []:
        if r.get("service") != service or r.get("unit") != unit:
            continue
        rs, rt = r.get("source_lang"), r.get("target_lang")
        if rt is not None and not _covers(rt, t):
            continue
        if rs is not None and not _covers(rs, s):
            continue
        rank = 0 if (rs and rt) else 1 if rt else 2
        if best is None or rank < best[0]:
            best = (rank, r)
    if best is None:
        return None
    r = best[1]
    return Decimal(str(r["rate"])), str(r.get("currency") or v.currency)


def price(
    v: Vendor, source_lang: str, target_lang: str, service: str, words: int
) -> tuple[Decimal, Decimal, str, str] | None:
    """(amount, per-unit rate, unit, currency) for `words` words, minimum applied, or None
    when the vendor has no rate for the service."""
    per_word = rate_for(v, source_lang, target_lang, service, "word")
    if per_word is None:
        return None
    rate, cur = per_word
    amount = (rate * Decimal(max(words, 0))).quantize(Decimal("0.01"))
    minimum = rate_for(v, source_lang, target_lang, service, "minimum")
    if minimum is not None and minimum[1] == cur and amount < minimum[0]:
        amount = minimum[0].quantize(Decimal("0.01"))
    return amount, rate, "word", cur


# --------------------------------------------------------------------------- CSV import


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "yes", "y", "true", "da", "x")


def _split(value: str, seps: str = ";|,") -> list[str]:
    out = [value]
    for sep in seps:
        out = [part for chunk in out for part in chunk.split(sep)]
    return [x.strip() for x in out if x.strip()]


def import_csv(session: Session, org_id: str, data: bytes) -> dict[str, Any]:
    """Create or update vendors from a CSV file. Returns {created, updated, errors: [{row, error}]}."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("the CSV file must be UTF-8") from None
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise Invalid("the CSV needs a header row with at least a 'name' column")
    created = updated = 0
    errors: list[dict[str, Any]] = []
    for n, raw in enumerate(reader, start=2):
        if n - 1 > CSV_MAX_ROWS:
            errors.append({"row": n, "error": f"only the first {CSV_MAX_ROWS} rows are imported"})
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        try:
            with session.begin_nested():
                body = _row_to_vendor(row)
                existing = find_vendor(session, org_id, email=body.email and str(body.email), name=body.name)
                if existing is None:
                    create_vendor(session, org_id, body)
                    created += 1
                else:
                    patch = VendorPatch.model_validate(
                        {
                            k: v
                            for k, v in body.model_dump(exclude_unset=True).items()
                            if k in VendorPatch.model_fields
                        }
                    )
                    update_vendor(session, existing, patch)
                    updated += 1
        except Exception as e:  # one bad row never stops the import
            msg = getattr(e, "message", None) or str(e)
            errors.append({"row": n, "error": str(msg).splitlines()[0][:300]})
    return {"created": created, "updated": updated, "errors": errors}


def _row_to_vendor(row: dict[str, str]) -> VendorIn:
    data: dict[str, Any] = {"name": row.get("name", "")}
    for key in ("kind", "phone", "country", "status", "tax_id", "iban", "notes", "legal_name", "address"):
        if row.get(key):
            data[key] = row[key].lower() if key in ("kind", "status") else row[key]
    if row.get("email"):
        data["email"] = row["email"]
    services = [s.lower() for s in _split(row.get("services", ""), ";|")] or ["translation", "review"]
    pairs = []
    for p in _split(row.get("pairs", "")):
        for sep in (">", "-", "/"):
            if sep in p:
                s, t = p.split(sep, 1)
                pairs.append({"source_lang": s.strip(), "target_lang": t.strip(), "services": services})
                break
        else:
            raise Invalid(f"pair {p!r} must look like en>de")
    if pairs:
        data["pairs"] = pairs
    if row.get("domains"):
        data["domains"] = _split(row["domains"], ";|")
    cur = row.get("currency") or "EUR"
    data["currency"] = cur
    if row.get("rate_per_word"):
        data["rates"] = [
            {"service": s, "unit": "word", "rate": row["rate_per_word"].replace(",", ".")}
            for s in services
            if s in SERVICES
        ]
    if row.get("capacity_words_per_day"):
        data["capacity_words_per_day"] = int(row["capacity_words_per_day"])
    if row.get("rating"):
        data["rating"] = row["rating"].replace(",", ".")
    if row.get("nda_signed"):
        data["nda_signed"] = _truthy(row["nda_signed"])
    return VendorIn.model_validate(data)


# --------------------------------------------------------------------------- shared helpers


def next_number(session: Session, org_id: str, kind: str, prefix: str, when: datetime | None = None) -> str:
    """Next document number of the org's series, e.g. PO-2026-0001 (row-locked, gap-free per txn)."""
    from sqlalchemy.dialects.postgresql import insert

    year = (when or utcnow()).year
    session.execute(
        insert(NumberSeries)
        .values(id=new_id("nsr"), org_id=org_id, kind=kind, year=year, last=0)
        .on_conflict_do_nothing(index_elements=["org_id", "kind", "year"])
    )
    row = session.execute(
        select(NumberSeries)
        .where(NumberSeries.org_id == org_id, NumberSeries.kind == kind, NumberSeries.year == year)
        .with_for_update()
    ).scalar_one()
    row.last += 1
    session.flush()
    return f"{prefix}-{year}-{row.last:04d}"


def notify(to: str | None, subject: str, body: str, *, link: str | None = None) -> dict[str, Any]:
    """Send an e-mail through arbiter.notify when that module exists; otherwise log it.
    Returns the record kept on the assignment ({at, to, subject, channel})."""
    channel = "log"
    try:
        from arbiter import notify as mail  # type: ignore[attr-defined]

        send = getattr(mail, "send_email", None)
        if to and callable(send):
            send(to=to, subject=subject, text=body + (f"\n\n{link}" if link else ""))
            channel = "email"
    except Exception as e:  # missing module or a failed send: never blocks the business flow
        if not isinstance(e, ImportError):
            log.warning("vendor notification failed: %s", e)
    if channel == "log":
        log.info("vendor notification to %s: %s %s", to or "-", subject, link or "")
    return {"at": utcnow().isoformat(), "to": to, "subject": subject, "channel": channel}

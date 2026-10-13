"""Bank transfer fallback rail: SEPA pain.001 XML, plain CSV and Wise batch CSV (D-052).

No API call: `send` validates the payee's bank details and leaves the payout `sent` and
pending with provider_ref "bank:<idempotency key>". The admin then builds a batch file
(`build_batch`, POST /admin/payouts/bank-batch), uploads it in the bank or Wise web app, and
confirms each payout (POST /admin/payouts/{id}/complete) or the whole batch
(POST /admin/payout-batches/{id}/settle), which moves the ledger like any provider result.

Formats
  pain001   ISO 20022 customer credit transfer initiation pain.001.001.09, one PmtInf, SEPA
            service level, charges SLEV, EUR only. Debtor = ARBITER_PAYOUT_DEBTOR_* settings.
  csv       name, iban, bic, amount, currency, reference (for banks without pain.001 upload)
  wise_csv  Wise batch payment template columns (name, recipientEmail, paymentReference,
            receiverType, amountCurrency, amount, sourceCurrency, targetCurrency, IBAN, BIC).
            Check the column set against the current template in Wise before the first upload.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from arbiter.config import get_settings

FORMATS = ("pain001", "csv", "wise_csv")
_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def iban_valid(value: str) -> bool:
    """ISO 13616 mod-97 check."""
    iban = normalize_iban(value)
    if not _IBAN_RE.match(iban):
        return False
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in moved)
    return int(digits) % 97 == 1


def bic_valid(value: str) -> bool:
    return bool(_BIC_RE.match((value or "").replace(" ", "").upper()))


def validate_details(method: str, details: dict[str, Any]) -> dict[str, str]:
    """Normalised bank details or ValueError with a user-facing reason."""
    holder = str(details.get("account_holder") or details.get("name") or "").strip()
    if method == "sepa":
        iban = normalize_iban(str(details.get("iban") or ""))
        if not iban_valid(iban):
            raise ValueError("IBAN is not valid")
        bic = str(details.get("bic") or "").replace(" ", "").upper()
        if bic and not bic_valid(bic):
            raise ValueError("BIC is not valid")
        if not holder:
            raise ValueError("account holder name is required")
        return {"iban": iban, "bic": bic, "account_holder": holder[:70]}
    if method == "wise":
        email = str(details.get("email") or "").strip()
        iban = normalize_iban(str(details.get("iban") or ""))
        if "@" not in email and not iban_valid(iban):
            raise ValueError("Wise needs the recipient email or a valid IBAN")
        if not holder:
            raise ValueError("account holder name is required")
        out = {"email": email, "account_holder": holder[:70]}
        if iban:
            out["iban"] = iban
        return out
    raise ValueError(f"bank rail does not handle {method}")


class BankRail:
    name = "bank"

    def configured(self) -> bool:
        return True

    def send(
        self,
        *,
        idempotency_key: str,
        reviewer_id: str,
        amount: Decimal,
        currency: str,
        method: str,
        details: dict[str, Any],
    ):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        try:
            validate_details(method, details)
        except ValueError as e:
            return PayoutResult("failed", None, f"bank details: {e}")
        if method == "sepa" and currency.upper() != "EUR":
            return PayoutResult("failed", None, "SEPA transfers are EUR only; use Wise")
        return PayoutResult("pending", f"bank:{idempotency_key}")

    def poll(self, provider_ref: str):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        return PayoutResult("pending", provider_ref)  # confirmed by the admin, not polled


# ------------------------------------------------------------------ batch files


def _amount(v: Decimal) -> str:
    return str(Decimal(v).quantize(Decimal("0.01")))


def pain001(batch_id: str, items: list[dict[str, Any]], execution: date | None = None) -> bytes:
    """items: [{end_to_end_id, name, iban, bic, amount (Decimal), reference}] (EUR)."""
    s = get_settings()
    debtor_iban = normalize_iban(s.payout_debtor_iban)
    if not s.payout_debtor_name or not iban_valid(debtor_iban):
        raise ValueError("set ARBITER_PAYOUT_DEBTOR_NAME and a valid ARBITER_PAYOUT_DEBTOR_IBAN first")
    total = sum((Decimal(i["amount"]) for i in items), Decimal("0"))
    from arbiter.models import utcnow

    now = utcnow().replace(microsecond=0).isoformat().replace("+00:00", "")
    day = (execution or utcnow().date()).isoformat()
    txs = []
    for i in items:
        agent = (
            f"<CdtrAgt><FinInstnId><BICFI>{escape(i['bic'])}</BICFI></FinInstnId></CdtrAgt>"
            if i.get("bic")
            else ""
        )
        txs.append(
            "<CdtTrfTxInf>"
            f"<PmtId><EndToEndId>{escape(i['end_to_end_id'][:35])}</EndToEndId></PmtId>"
            f'<Amt><InstdAmt Ccy="EUR">{_amount(i["amount"])}</InstdAmt></Amt>'
            f"{agent}"
            f"<Cdtr><Nm>{escape(i['name'][:70])}</Nm></Cdtr>"
            f"<CdtrAcct><Id><IBAN>{escape(i['iban'])}</IBAN></Id></CdtrAcct>"
            f"<RmtInf><Ustrd>{escape(i['reference'][:140])}</Ustrd></RmtInf>"
            "</CdtTrfTxInf>"
        )
    debtor_agent = (
        f"<DbtrAgt><FinInstnId><BICFI>{escape(s.payout_debtor_bic)}</BICFI></FinInstnId></DbtrAgt>"
        if s.payout_debtor_bic
        else "<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>"
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">'
        "<CstmrCdtTrfInitn>"
        f"<GrpHdr><MsgId>{escape(batch_id[:35])}</MsgId><CreDtTm>{now}</CreDtTm>"
        f"<NbOfTxs>{len(items)}</NbOfTxs><CtrlSum>{_amount(total)}</CtrlSum>"
        f"<InitgPty><Nm>{escape(s.payout_debtor_name[:70])}</Nm></InitgPty></GrpHdr>"
        f"<PmtInf><PmtInfId>{escape(batch_id[:35])}</PmtInfId><PmtMtd>TRF</PmtMtd>"
        f"<NbOfTxs>{len(items)}</NbOfTxs><CtrlSum>{_amount(total)}</CtrlSum>"
        "<PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>"
        f"<ReqdExctnDt><Dt>{day}</Dt></ReqdExctnDt>"
        f"<Dbtr><Nm>{escape(s.payout_debtor_name[:70])}</Nm></Dbtr>"
        f"<DbtrAcct><Id><IBAN>{debtor_iban}</IBAN></Id></DbtrAcct>"
        f"{debtor_agent}<ChrgBr>SLEV</ChrgBr>" + "".join(txs) + "</PmtInf></CstmrCdtTrfInitn></Document>"
    )
    return xml.encode("utf-8")


def plain_csv(items: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name", "iban", "bic", "email", "amount", "currency", "reference"])
    for i in items:
        w.writerow(
            [
                i["name"],
                i.get("iban", ""),
                i.get("bic", ""),
                i.get("email", ""),
                _amount(i["amount"]),
                i["currency"],
                i["reference"],
            ]
        )
    return buf.getvalue().encode("utf-8")


def wise_csv(items: list[dict[str, Any]], source_currency: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "name",
            "recipientEmail",
            "paymentReference",
            "receiverType",
            "amountCurrency",
            "amount",
            "sourceCurrency",
            "targetCurrency",
            "IBAN",
            "BIC",
        ]
    )
    for i in items:
        w.writerow(
            [
                i["name"],
                i.get("email", ""),
                i["reference"][:35],
                "PRIVATE",
                "target",
                _amount(i["amount"]),
                source_currency.upper(),
                i["currency"],
                i.get("iban", ""),
                i.get("bic", ""),
            ]
        )
    return buf.getvalue().encode("utf-8")

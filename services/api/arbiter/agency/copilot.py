"""PM copilot (module pm): the assistant's project-management tools.

The assistant (arbiter.agency.assistant) stays plan-then-apply. For a PM question it calls
pm_query() BEFORE the model: the question is parsed (heuristic_pm.parse_pm) and answered from
the database here (capacity planner, deadline risk, assignment suggestions, price lists). The
result goes into the model's context as context["pm"]["query"] (so a real model answers from
facts, never from guesses) and, with the built-in planner, heuristic_pm.pm_answer() writes the
reply and plan. pm_context() adds a short vendor and risk summary to every context.

Plan actions this module applies (always by a human, like every plan action):
  create_assignment  {job_id, step, mode, vendor_ids, strategy, ...} -> assignments.create
  draft_quote        {account_id, source_lang, target_langs, words, tier, file_id?} -> a CRM deal
                     in stage proposal valued at the estimate (and a real quote with TM analysis
                     when file_id is given)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.agency import assignments, capacity, pricelists
from arbiter.agency.common import HUMANLESS_TIERS, iso, money
from arbiter.agency.heuristic import fold
from arbiter.agency.heuristic_pm import parse_pm
from arbiter.agency.vendor_schemas import AssignmentIn, CreateAssignmentData, DraftQuoteData
from arbiter.billing import pricing
from arbiter.config import get_settings
from arbiter.errors import Invalid, NotFound
from arbiter.models import (
    CrmAccount,
    CrmActivity,
    CrmDeal,
    FileAsset,
    Job,
    Organization,
    PriceList,
    Project,
    Vendor,
    utcnow,
)
from arbiter.platform.modules import org_has_module

CENT = Decimal("0.01")
OPEN_JOB_STATES = ("draft", "quoted", "running", "review")


def enabled(org: Organization) -> bool:
    return org_has_module(org, "pm")


# --------------------------------------------------------------------------- context


def pm_context(session: Session, org: Organization) -> dict[str, Any]:
    """Compact vendor, account and risk summary for the assistant's context."""
    vendors = list(
        session.execute(
            select(Vendor)
            .where(Vendor.org_id == org.id, Vendor.status == "active")
            .order_by(Vendor.name)
            .limit(40)
        ).scalars()
    )
    accounts = session.execute(
        select(CrmAccount.id, CrmAccount.name, CrmAccount.price_list_id, CrmAccount.default_tier)
        .where(CrmAccount.org_id == org.id, CrmAccount.status == "active")
        .order_by(CrmAccount.name)
        .limit(40)
    ).all()
    risk = capacity.deadline_risk(session, org.id, only_at_risk=True)
    return {
        "vendors": [
            {
                "id": v.id,
                "name": v.name,
                "pairs": [f"{p['source_lang']}>{p['target_lang']}" for p in v.pairs or []],
                "capacity_words_per_day": v.capacity_words_per_day,
            }
            for v in vendors
        ],
        "accounts": [
            {"id": i, "name": n, "price_list_id": pl, "default_tier": t} for i, n, pl, t in accounts
        ],
        "jobs_at_risk": [
            {
                k: r[k]
                for k in ("job_id", "project", "due_at", "estimated_finish", "remaining_words", "reasons")
            }
            for r in risk[:10]
        ],
    }


# --------------------------------------------------------------------------- queries


def _find_job(session: Session, org: Organization, q: dict[str, Any]) -> tuple[Job, str | None] | None:
    if q.get("job_id"):
        row = session.execute(
            select(Job, Project.name)
            .join(Project, Project.id == Job.project_id)
            .where(Job.org_id == org.id, func.lower(Job.id) == q["job_id"].lower())
        ).first()
        return (row[0], row[1]) if row else None
    rows = session.execute(
        select(Job, Project.name)
        .join(Project, Project.id == Job.project_id)
        .where(Job.org_id == org.id, Job.state.in_(OPEN_JOB_STATES))
        .order_by(Job.created_at.desc(), Job.id)
        .limit(200)
    ).all()
    text = q["folded"]
    hits = [(j, n) for j, n in rows if n and len(n) >= 3 and fold(n) in text]
    if q.get("target_lang"):
        hits = [(j, n) for j, n in hits if j.target_lang.lower().startswith(q["target_lang"])] or hits
    return hits[0] if hits else None


def _find_account(session: Session, org: Organization, folded: str) -> CrmAccount | None:
    accounts = list(
        session.execute(
            select(CrmAccount).where(CrmAccount.org_id == org.id, CrmAccount.status == "active")
        ).scalars()
    )
    hits = [a for a in accounts if len(a.name) >= 2 and fold(a.name) in folded]
    return max(hits, key=lambda a: len(a.name)) if hits else None


def quote_estimate(
    session: Session,
    org: Organization,
    account: CrmAccount,
    source_lang: str,
    target_langs: list[str],
    words: int,
    tier: str,
) -> dict[str, Any]:
    """Price for `words` words per target language from the client's price list (org default
    rates without one), minimum charge applied once to the total, like billing.quotes."""
    pl = None
    if account.price_list_id:
        pl = session.get(PriceList, account.price_list_id)
        if pl is not None and (pl.org_id != org.id or pl.archived_at is not None):
            pl = None
    lines = []
    subtotal = Decimal("0")
    for t in target_langs:
        if pl is not None:
            rate, rule = pricelists.rate_for(pl, source_lang, t, tier, org)
        else:
            rate, rule = pricing.tier_rates(org)[tier], "org_default"
        amount = (rate * Decimal(words)).quantize(CENT, rounding=ROUND_HALF_UP)
        subtotal += amount
        lines.append({"target_lang": t, "per_word": str(rate), "rule": rule, "amount": money(amount)})
    minimum = pricelists.minimum_for(pl, org) if pl is not None else pricing.minimum_charge(org)
    total = max(minimum, subtotal)
    return {
        "account_id": account.id,
        "account_name": account.name,
        "price_list_id": pl.id if pl else None,
        "currency": pl.currency if pl else get_settings().currency,
        "source_lang": source_lang,
        "target_langs": target_langs,
        "words": words,
        "tier": tier,
        "lines": lines,
        "subtotal": money(subtotal),
        "total": money(total),
        "minimum_applied": total > subtotal,
    }


def pm_query(session: Session, org: Organization, text: str) -> dict[str, Any] | None:
    """Parse a PM question and compute its answer. None when it is not a PM question."""
    if not enabled(org):
        return None
    q = parse_pm(text, utcnow().date())
    if q is None:
        return None
    out: dict[str, Any] = {k: v for k, v in q.items() if k != "folded"}
    out["by"] = iso(q["by"])
    missing: list[str] = []
    intent = q["intent"]
    if intent == "capacity":
        if not (q["source_lang"] and q["target_lang"]):
            missing.append("Which language pair? For example: who is free for EN->DE 20k words by Friday?")
        if not q["words"]:
            missing.append("How many words?")
        if not missing:
            out["result"] = capacity.planner(
                session,
                org.id,
                source_lang=q["source_lang"],
                target_lang=q["target_lang"],
                words=q["words"],
                by=q["by"],
            )[:10]
    elif intent == "risk":
        out["result"] = capacity.deadline_risk(session, org.id)
    elif intent == "propose_assignment":
        found = _find_job(session, org, q)
        if found is None:
            missing.append(
                "Which job? Give me the job id (job_...) or the project name, for example: "
                "propose assignments for job job_01..."
            )
        else:
            job, project = found
            step = q["step"] if assignments.step_available(job, q["step"]) else "human_review"
            if not assignments.step_available(job, step):
                missing.append(f"Job {job.id} has no human review step (tier {job.tier}); nothing to assign.")
            else:
                sug = capacity.suggestions_for_job(session, job, step)
                out["step"] = step
                out["job"] = {
                    "job_id": job.id,
                    "project": project,
                    "source_lang": job.source_lang,
                    "target_lang": job.target_lang,
                    "words": sug["words"],
                    "due_at": iso(job.due_at),
                    "state": job.state,
                }
                out["result"] = sug["items"][:10]
    elif intent == "draft_quote":
        account = _find_account(session, org, q["folded"])
        if account is None:
            names = ", ".join(
                session.execute(
                    select(CrmAccount.name)
                    .where(CrmAccount.org_id == org.id, CrmAccount.status == "active")
                    .order_by(CrmAccount.name)
                    .limit(10)
                ).scalars()
            )
            missing.append("Which client is the quote for?" + (f" Your clients: {names}." if names else ""))
        if not (q["source_lang"] and q["target_lang"]):
            missing.append("Which language pair (for example EN->DE)?")
        if not q["words"]:
            missing.append("How many words?")
        if not missing and account is not None:
            tier = q["tier"] or account.default_tier or org.default_tier or "full"
            if org.regulated and tier in HUMANLESS_TIERS:
                tier = "full"  # R-SEG-12
            out["result"] = quote_estimate(
                session, org, account, q["source_lang"], [q["target_lang"]], int(q["words"]), tier
            )
    if missing:
        out["missing"] = missing
    return out


# --------------------------------------------------------------------------- apply


def apply_create_assignment(
    session: Session, org: Organization, data: dict[str, Any], user_id: str | None
) -> tuple[str, str | None]:
    if not enabled(org):
        raise Invalid("the project management module is not enabled")
    body = CreateAssignmentData.model_validate(data)
    rows = assignments.create(
        session, org, body.job_id, AssignmentIn.model_validate(body.model_dump(exclude={"job_id"})), user_id
    )
    if not rows:
        return body.job_id, "the step is on the reviewer marketplace"
    first = rows[0]
    v = session.get(Vendor, first.vendor_id) if first.vendor_id else None
    return first.id, f"offered to {v.name}" if v else None


def apply_draft_quote(
    session: Session, org: Organization, data: dict[str, Any], user_id: str | None
) -> tuple[str, str | None]:
    from arbiter.billing.quotes import build_quote

    body = DraftQuoteData.model_validate(data)
    account = session.get(CrmAccount, body.account_id)
    if account is None or account.org_id != org.id:
        raise NotFound("account not found")
    tier = body.tier
    if org.regulated and tier in HUMANLESS_TIERS:
        raise Invalid("Regulated vertical: every segment needs a human reviewer (R-SEG-12).")
    est = quote_estimate(session, org, account, body.source_lang, body.target_langs, body.words, tier)
    quote_id = None
    if body.file_id:
        fa = session.get(FileAsset, body.file_id)
        if fa is None or fa.org_id != org.id or fa.deleted_at is not None:
            raise NotFound("file not found")
        pl = session.get(PriceList, est["price_list_id"]) if est["price_list_id"] else None
        quote_id = build_quote(session, org, fa, body.target_langs, price_list=pl, account_id=account.id).id
    title = body.title or (
        f"Quote: {body.words} words {body.source_lang}>{', '.join(body.target_langs)} ({tier})"
    )
    deal = CrmDeal(
        org_id=org.id,
        account_id=account.id,
        title=title[:300],
        value=Decimal(est["total"]),
        currency=est["currency"],
        stage="proposal",
        quote_id=quote_id,
        owner_user_id=user_id,
    )
    session.add(deal)
    session.flush()
    breakdown = "; ".join(f"{x['target_lang']}: {x['per_word']}/word = {x['amount']}" for x in est["lines"])
    session.add(
        CrmActivity(
            org_id=org.id,
            account_id=account.id,
            deal_id=deal.id,
            kind="note",
            body=f"Draft quote {est['total']} {est['currency']} ({breakdown}"
            + (", minimum charge applied" if est["minimum_applied"] else "")
            + ").",
            user_id=user_id,
        )
    )
    session.flush()
    return deal.id, f"deal in stage proposal, {est['total']} {est['currency']}"

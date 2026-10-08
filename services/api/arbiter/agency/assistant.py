"""The Agency OS assistant: plain-language description in, reviewable plan of actions out.

Flow (POST /assistant/threads/{id}/messages):
  1. build_context(): a compact summary of the org (accounts, deals by stage, workflows,
     price lists, recent and overdue jobs, revenue and margin over 90 days...). It is the
     ONLY data the model sees and the only source for answers about the org.
  2. The model (settings.default_judge_engine via engines.registry.get_llm, the same
     LlmClient.complete_json every judge uses) gets SYSTEM_PROMPT plus a JSON user turn
     {"task": "assistant", context, history, message} and answers {"reply", "plan"}.
     When the client is a mock (name starts with "mock"), or the model is unavailable or
     fails, heuristic_plan() (arbiter.agency.heuristic) answers instead, deterministically.
  3. validate_plan(): every action is checked with the pydantic models of the matching
     endpoint plus semantic rules (workflow validation, widget metrics, R-SEG-12, "@index"
     references, names and e-mails must come from the user's own words). Invalid actions
     are dropped and the reply says so.
The assistant never changes anything itself. apply() executes the selected actions in
order, each in its own savepoint (one failing action never undoes the others), records
the applied indices and what each created, and skips indices already applied (idempotent).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arbiter import webhooks
from arbiter.agency import crm, dashboards, pricelists
from arbiter.agency import workflows as wfl
from arbiter.agency.common import HUMANLESS_TIERS, REGULATED_REASON, iso
from arbiter.agency.heuristic import fold, heuristic_plan
from arbiter.agency.org import update_org
from arbiter.agency.schemas import (
    AccountIn,
    ActivityIn,
    ContactIn,
    DashboardIn,
    DealIn,
    PriceListIn,
    Tier,
    WorkflowIn,
)
from arbiter.config import get_settings
from arbiter.contracts import EngineError, LlmClient
from arbiter.engines.registry import get_llm
from arbiter.errors import Conflict, Invalid, NotFound, ServiceError
from arbiter.linguistic import glossary as gl
from arbiter.models import (
    AssistantMessage,
    AssistantThread,
    CrmAccount,
    CrmActivity,
    CrmContact,
    Dashboard,
    Glossary,
    Job,
    Organization,
    PriceList,
    Project,
    Webhook,
    WorkflowTemplate,
    utcnow,
)

log = logging.getLogger(__name__)

ASSISTANT_PROMPT_VERSION = "2026-10-08.1"
HISTORY_TURNS = 10
ACTION_TYPES = (
    "create_workflow",
    "create_price_list",
    "create_account",
    "create_contact",
    "create_deal",
    "create_activity",
    "create_dashboard",
    "update_org",
    "create_glossary",
    "add_terms",
    "create_webhook",
)
REF = re.compile(r"^@(\d{1,3})$")

SYSTEM_PROMPT = """You are the setup assistant of Arbiter, an AI translation platform that agencies and
localization teams run their business on (projects, CRM, workflows, prices, dashboards).
The user describes their agency or team in plain language (any language) or asks about their
data. You propose a PLAN of configuration actions. You never change anything yourself: a
human reviews the plan and applies all or some actions.

Output language: the request carries "locale" (a BCP-47 tag, e.g. en, de, pt-BR). Write
"reply", every "summary" and every name YOU choose (workflow, price list and dashboard names,
workflow descriptions, widget titles) in that locale, whatever language the user wrote in.
Proper names the user gave (agency, clients, contacts, e-mails) are kept exactly as written.

Output: one JSON object and nothing else:
{"reply": "<message to the user>", "plan": [<Action>, ...]}
Action = {"type": "<one of the types below>", "summary": "<one line, in the locale>", "data": {...}}

Action types and their data (fields marked ? are optional; money and rates are decimal strings):
- update_org: {name?, vertical?, regulated?, default_tier?, no_reviewer_policy? (wait|ai_fallback|partial)}
- create_workflow: {name, description?, content_type?, tier (auto|ai_review|hybrid|full),
    steps: [{kind, params?}], is_default?}
  Step kinds, in this order when present: tm (TM pre-translation), mt (params.engine?),
  translation_senate (best-of-N across engines), qe (params.threshold? 0-100), senate (review
  senate for uncertain scores), ai_review (senate + AI editor, no human), human_review
  (params.min_level? reviewer|senior|domain_expert), second_review (a second senior human),
  client_review (the client approves before delivery), delivery.
  Rules: contains mt or tm; each kind once; qe before any review step; second_review after
  human_review; delivery last. Tier must match: full needs human_review; auto has no
  human_review, second_review or ai_review; ai_review has no human_review or second_review;
  hybrid sends only low scores to a human.
- create_price_list: {name, currency (ISO, e.g. EUR), rates: [{source_lang?, target_lang?, tier,
    per_word}], tm_weights? {context, exact, fuzzy_95, fuzzy_85, fuzzy_75, new, repetition},
    minimum_charge?}
- create_account: {name, kind (client|prospect), industry?, country? (2 letters), vat_id?,
    currency?, default_tier?, workflow_template_id?, price_list_id?, notes?}
- create_contact: {account_id, name, email?, phone?, role?, is_primary?}
- create_deal: {account_id, title, value, currency?, stage? (lead|qualified|proposal|negotiation|won|lost),
    expected_close? (YYYY-MM-DD)}
- create_activity: {account_id, deal_id?, kind (note|call|email|meeting|task), body, due_at?}
- create_dashboard: {name, widgets: [{type, metric, title?, size? (s|m|l)}]}
  kpi metrics: revenue, margin, margin_pct, jobs_active, jobs_overdue, auto_rate, escaped_rate,
  open_deals_value, words_delivered, reviewer_cost. bar or line metrics: revenue_by_month,
  jobs_by_state, revenue_by_account, words_by_pair, auto_rate_by_month. pipeline metric:
  deals_by_stage. table metrics: overdue_jobs, top_accounts, open_activities, recent_deliveries.
- create_glossary: {name, content_type?}
- add_terms: {glossary_id, terms: [{source_lang, target_lang, source_term, target_term?,
    kind (mandatory|preferred|forbidden|do_not_translate), note?}]}
- create_webhook: {url, events: [job.delivered|job.failed|job.needs_attention|quote.expired]}

References: an id field may point at an object created by an EARLIER action of the same
plan as "@<index>" (0-based), e.g. an account with "price_list_id": "@2" and
"workflow_template_id": "@1". Existing objects are referenced by the ids in the context.

Rules:
1. Turn the description into concrete actions: organization name and vertical, one workflow
   per distinct process (a stricter workflow for clients or domains that need it, linked
   from those accounts), a price list from the rates given, one account per client named,
   contacts only for people named, a dashboard with widgets for what they want to track.
2. Never invent client names, contact names, e-mail addresses, prices or numbers. Use only
   what the user wrote or what the context contains.
3. When essential information is missing (agency name, clients, prices, workflow, language
   pairs), still propose what you can and ask short clarifying questions in "reply".
4. Regulated organizations (context.org.regulated, or medical, legal, pharma work the user
   says is regulated) never get tier auto or ai_review (rule R-SEG-12): use hybrid or full.
5. Questions about the org's data (jobs, overdue work, revenue, margin, deals, clients) are
   answered from the context only, with exact numbers, and an empty plan. If the context does
   not contain the answer, say so.
6. Steps the platform does not have (for example DTP or layout) are left out and mentioned in
   "reply". Reviewers cannot be created by a plan; they join through the reviewer community.
7. Keep "reply" short and concrete: what the plan does and any questions. Do not repeat every
   field of every action.
"""


# --------------------------------------------------------------------------- action models


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrgData(_Data):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    vertical: str | None = Field(default=None, max_length=60)
    regulated: bool | None = None
    default_tier: Tier | None = None
    no_reviewer_policy: Literal["wait", "ai_fallback", "partial"] | None = None


class ContactData(ContactIn):
    account_id: str = Field(min_length=1, max_length=40)


class GlossaryData(_Data):
    name: str = Field(min_length=1, max_length=200)
    content_type: str | None = Field(default=None, max_length=60)


class TermData(_Data):
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    source_term: str = Field(min_length=1, max_length=500)
    target_term: str | None = Field(default=None, max_length=500)
    kind: Literal["mandatory", "preferred", "forbidden", "do_not_translate"] = "mandatory"
    note: str = Field(default="", max_length=2000)


class TermsData(_Data):
    glossary_id: str = Field(min_length=1, max_length=40)
    terms: list[TermData] = Field(min_length=1, max_length=500)


class WebhookData(_Data):
    url: str = Field(min_length=8, max_length=1000)
    events: list[str] = Field(min_length=1, max_length=20)


DATA_MODELS: dict[str, type[BaseModel]] = {
    "create_workflow": WorkflowIn,
    "create_price_list": PriceListIn,
    "create_account": AccountIn,
    "create_contact": ContactData,
    "create_deal": DealIn,
    "create_activity": ActivityIn,
    "create_dashboard": DashboardIn,
    "update_org": OrgData,
    "create_glossary": GlossaryData,
    "add_terms": TermsData,
    "create_webhook": WebhookData,
}
# Reference fields: data key -> action type that must create the referenced object.
REF_FIELDS: dict[str, dict[str, str]] = {
    "create_account": {"workflow_template_id": "create_workflow", "price_list_id": "create_price_list"},
    "create_contact": {"account_id": "create_account"},
    "create_deal": {"account_id": "create_account"},
    "create_activity": {"account_id": "create_account", "deal_id": "create_deal"},
    "add_terms": {"glossary_id": "create_glossary"},
}
REQUIRED_REFS = {"account_id", "glossary_id"}


class Action(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "create_workflow",
        "create_price_list",
        "create_account",
        "create_contact",
        "create_deal",
        "create_activity",
        "create_dashboard",
        "update_org",
        "create_glossary",
        "add_terms",
        "create_webhook",
    ]
    summary: str = Field(default="", max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- context


def build_context(session: Session, org: Organization) -> dict[str, Any]:
    """The org summary the assistant reasons over (and the only data it may quote)."""
    org_id = org.id
    now = utcnow()
    accounts = session.execute(
        select(CrmAccount.kind, func.count())
        .where(CrmAccount.org_id == org_id, CrmAccount.status == "active")
        .group_by(CrmAccount.kind)
    ).all()
    by_kind = {k: int(n) for k, n in accounts}
    names = list(
        session.execute(
            select(CrmAccount.name)
            .where(CrmAccount.org_id == org_id, CrmAccount.status == "active")
            .order_by(CrmAccount.name)
            .limit(30)
        ).scalars()
    )
    contacts = session.execute(
        select(func.count()).select_from(CrmContact).where(CrmContact.org_id == org_id)
    ).scalar_one()
    pipe = dashboards.compute_metric(session, org_id, "pipeline", "deals_by_stage", "90d")
    open_deals = dashboards.compute_metric(session, org_id, "kpi", "open_deals_value", "90d")
    wfs = session.execute(
        select(WorkflowTemplate)
        .where(WorkflowTemplate.org_id == org_id, WorkflowTemplate.archived_at.is_(None))
        .order_by(WorkflowTemplate.created_at)
        .limit(20)
    ).scalars()
    pls = session.execute(
        select(PriceList)
        .where(PriceList.org_id == org_id, PriceList.archived_at.is_(None))
        .order_by(PriceList.created_at)
        .limit(20)
    ).scalars()
    dashes = session.execute(
        select(Dashboard.id, Dashboard.name).where(Dashboard.org_id == org_id).order_by(Dashboard.created_at)
    ).all()
    glossaries = session.execute(
        select(Glossary.id, Glossary.name).where(Glossary.org_id == org_id).order_by(Glossary.name).limit(20)
    ).all()
    active = dashboards.compute_metric(session, org_id, "kpi", "jobs_active")["value"]
    overdue_tbl = dashboards.compute_metric(session, org_id, "table", "overdue_jobs")
    overdue = dashboards.compute_metric(session, org_id, "kpi", "jobs_overdue")["value"]
    by_state = dict(
        session.execute(select(Job.state, func.count()).where(Job.org_id == org_id).group_by(Job.state)).all()
    )
    recent = session.execute(
        select(Job, Project.name, CrmAccount.name)
        .join(Project, Project.id == Job.project_id)
        .outerjoin(CrmAccount, CrmAccount.id == Job.account_id)
        .where(Job.org_id == org_id)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(10)
    ).all()
    revenue = dashboards.compute_metric(session, org_id, "kpi", "revenue", "90d")["value"]
    margin = dashboards.compute_metric(session, org_id, "kpi", "margin", "90d")["value"]
    words = dashboards.compute_metric(session, org_id, "kpi", "words_delivered", "90d")["value"]
    open_acts = session.execute(
        select(func.count())
        .select_from(CrmActivity)
        .where(CrmActivity.org_id == org_id, CrmActivity.done.is_(False))
    ).scalar_one()
    return {
        "today": now.date().isoformat(),
        "currency": get_settings().currency,
        "org": {
            "name": org.name,
            "vertical": org.vertical,
            "regulated": org.regulated,
            "default_tier": org.default_tier,
            "no_reviewer_policy": org.no_reviewer_policy,
        },
        "accounts": {
            "active": sum(by_kind.values()),
            "clients": by_kind.get("client", 0),
            "prospects": by_kind.get("prospect", 0),
            "names": names,
        },
        "contacts": int(contacts),
        "deals": {
            "by_stage": {s["stage"]: {"count": s["count"], "value": s["value"]} for s in pipe["stages"]},
            "open_value": open_deals["value"],
            "open_count": open_deals.get("count", 0),
        },
        "workflows": [
            {"id": w.id, "name": w.name, "tier": w.tier, "steps": [s.get("kind") for s in w.steps or []]}
            for w in wfs
        ],
        "price_lists": [
            {"id": p.id, "name": p.name, "currency": p.currency, "rates": len(p.rates or [])} for p in pls
        ],
        "dashboards": [{"id": i, "name": n} for i, n in dashes],
        "glossaries": [{"id": i, "name": n} for i, n in glossaries],
        "jobs": {
            "active": active,
            "overdue": overdue,
            "by_state": {k: int(v) for k, v in by_state.items()},
            "overdue_list": overdue_tbl["rows"][:10],
            "recent": [
                {
                    "job_id": j.id,
                    "project": pname,
                    "account": aname,
                    "state": j.state,
                    "target_lang": j.target_lang,
                    "words": j.word_count,
                    "due_at": iso(j.due_at),
                    "overdue": bool(
                        j.due_at and j.due_at < now and j.state not in dashboards.FINAL_JOB_STATES
                    ),
                }
                for j, pname, aname in recent
            ],
        },
        "revenue_90d": revenue,
        "margin_90d": margin,
        "words_delivered_90d": words,
        "open_activities": int(open_acts),
    }


# --------------------------------------------------------------------------- validation


def _user_text(session: Session, thread: AssistantThread, latest: str) -> str:
    texts = list(
        session.execute(
            select(AssistantMessage.content).where(
                AssistantMessage.thread_id == thread.id, AssistantMessage.role == "user"
            )
        ).scalars()
    )
    return fold(" ".join([*texts, latest]))


def _norm(s: str) -> str:
    return " ".join(fold(s).split())


def _given(value: str, user_text: str) -> bool:
    """A name or e-mail is acceptable only if the user wrote it (case/diacritics-insensitive)."""
    return _norm(value) in " ".join(user_text.split())


def validate_plan(
    raw: Any, org: Organization, user_text: str, *, check_names: bool = True
) -> tuple[list[dict[str, Any]], list[str]]:
    """(valid actions with refs renumbered, one note per dropped action)."""
    if not isinstance(raw, list):
        return [], ["the plan was not a list"] if raw not in (None, []) else []
    notes: list[str] = []
    kept: list[dict[str, Any]] = []
    new_index: dict[int, int] = {}
    kept_types: dict[int, str] = {}
    regulated = org.regulated
    for i, item in enumerate(raw[:50]):
        try:
            act = Action.model_validate(item)
            data = dict(act.data)
            refs = REF_FIELDS.get(act.type, {})
            for key, want in refs.items():
                val = data.get(key)
                if isinstance(val, str) and (m := REF.match(val)):
                    old = int(m.group(1))
                    if old not in new_index or kept_types[old] != want:
                        if key in REQUIRED_REFS:
                            raise Invalid(f"{key} points at action {old}, which is not a valid {want}")
                        data.pop(key)
                        notes.append(f"action {i}: dropped the link {key} (action {old} is not valid)")
                    else:
                        data[key] = f"@{new_index[old]}"
            model = DATA_MODELS[act.type].model_validate(data)
            clean = model.model_dump(mode="json", exclude_none=True)
            _semantic_check(act.type, model, org, regulated)
            if act.type == "update_org" and clean.get("regulated") is not None:
                regulated = bool(clean["regulated"])
            if check_names and act.type in ("create_account", "create_contact"):
                if not _given(clean["name"], user_text):
                    raise Invalid(f"the name {clean['name']!r} was not given by the user")
                if clean.get("email") and not _given(clean["email"], user_text):
                    raise Invalid(f"the e-mail {clean['email']!r} was not given by the user")
            summary = act.summary.strip() or act.type.replace("_", " ")
            new_index[i] = len(kept)
            kept_types[i] = act.type
            kept.append({"type": act.type, "summary": summary[:300], "data": clean})
        except (ValidationError, ServiceError, ValueError, TypeError) as e:
            kind = item.get("type") if isinstance(item, dict) else None
            notes.append(f"action {i} ({kind or 'unknown'}): {_short_error(e)}")
    return kept, notes


def _short_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        return f"{loc}: {first.get('msg')}" if loc else str(first.get("msg"))
    return str(getattr(e, "message", None) or e)[:300]


def _semantic_check(kind: str, model: BaseModel, org: Organization, regulated: bool) -> None:
    if kind == "create_workflow":
        assert isinstance(model, WorkflowIn)
        wfl.validate_steps(model.steps, model.tier, regulated=regulated)
    elif kind == "create_dashboard":
        assert isinstance(model, DashboardIn)
        dashboards.validate_widgets(model.widgets)
    elif kind == "create_price_list":
        assert isinstance(model, PriceListIn)
        pricelists._rates(model.rates)  # noqa: SLF001  (duplicate check)
    elif kind == "create_account":
        assert isinstance(model, AccountIn)
        if regulated and model.default_tier in HUMANLESS_TIERS:
            raise Invalid(REGULATED_REASON)
    elif kind == "update_org":
        assert isinstance(model, OrgData)
        reg = model.regulated if model.regulated is not None else regulated
        if reg and model.default_tier in HUMANLESS_TIERS:
            raise Invalid(REGULATED_REASON)
    elif kind == "create_webhook":
        assert isinstance(model, WebhookData)
        webhooks.check_url(model.url)
        bad = [e for e in model.events if e not in webhooks.EVENTS]
        if bad:
            raise Invalid(f"unknown webhook event(s): {', '.join(bad)}")


# --------------------------------------------------------------------------- the model call


def _llm() -> LlmClient:
    """The assistant's model: the configured judge engine (tests monkeypatch this)."""
    return get_llm(get_settings().default_judge_engine)


def _history(session: Session, thread: AssistantThread) -> list[dict[str, Any]]:
    rows = list(
        session.execute(
            select(AssistantMessage)
            .where(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(HISTORY_TURNS)
        ).scalars()
    )
    out = []
    for m in reversed(rows):
        turn: dict[str, Any] = {"role": m.role, "content": m.content[:4000]}
        if m.plan:
            turn["plan"] = [{"type": a.get("type"), "summary": a.get("summary")} for a in m.plan]
            turn["applied"] = list(m.applied or [])
        out.append(turn)
    return out


def think(
    session: Session, org: Organization, thread: AssistantThread, content: str, locale: str = "en"
) -> tuple[str, list[dict[str, Any]], str]:
    """(reply, validated plan, model_version) for one user message, answered in `locale`."""
    context = build_context(session, org)
    user_text = _user_text(session, thread, content)
    fallback_note = ""
    try:
        llm = _llm()
    except EngineError as e:
        llm = None
        fallback_note = f"The AI model is not available ({e}); this answer comes from the built-in planner."
    if llm is not None and not llm.name.startswith("mock"):
        user = json.dumps(
            {
                "task": "assistant",
                "prompt_version": ASSISTANT_PROMPT_VERSION,
                "locale": locale,
                "context": context,
                "history": _history(session, thread),
                "message": content,
            },
            ensure_ascii=False,
            default=str,
        )
        try:
            answer, _usage, model_version = llm.complete_json(
                SYSTEM_PROMPT,
                user,
                schema_hint='{"reply": "...", "plan": [{"type": "...", "summary": "...", "data": {}}]}',
                max_tokens=6000,
                temperature=0.2,
            )
            reply = answer.get("reply") if isinstance(answer, dict) else None
            if not isinstance(reply, str) or not reply.strip():
                raise EngineError("the model returned no reply")
            plan, notes = validate_plan(answer.get("plan") or [], org, user_text)
            if notes:
                reply = (
                    reply.rstrip()
                    + "\n\n"
                    + (
                        f"Note: {len(notes)} proposed action(s) were dropped because they were not valid:\n"
                        + "\n".join(f"- {n}" for n in notes)
                    )
                )
            return reply.strip(), plan, f"{model_version}|{ASSISTANT_PROMPT_VERSION}"
        except EngineError as e:
            log.warning("assistant model failed, using the built-in planner: %s", e)
            fallback_note = "The AI model failed to answer; this answer comes from the built-in planner."
    reply, raw = heuristic_plan(content, context, locale)
    plan, notes = validate_plan(raw, org, user_text)
    if notes:
        reply += "\n\n" + "\n".join(f"- {n}" for n in notes)
    if fallback_note:
        reply = f"{reply}\n\n({fallback_note})"
    return reply, plan, f"heuristic|{ASSISTANT_PROMPT_VERSION}"


# --------------------------------------------------------------------------- threads & messages


def thread_view(t: AssistantThread, messages: list[AssistantMessage] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": t.id,
        "title": t.title,
        "user_id": t.user_id,
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
    }
    if messages is not None:
        out["messages"] = [message_view(m) for m in messages]
    return out


def message_view(m: AssistantMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "thread_id": m.thread_id,
        "role": m.role,
        "content": m.content,
        "plan": [dict(a) for a in m.plan] if m.plan is not None else None,
        "applied": list(m.applied or []),
        "results": {k: dict(v) for k, v in (m.results or {}).items()},
        "created_at": iso(m.created_at),
    }


def get_thread(session: Session, org_id: str, thread_id: str, *, lock: bool = False) -> AssistantThread:
    q = select(AssistantThread).where(AssistantThread.id == thread_id, AssistantThread.org_id == org_id)
    if lock:
        q = q.with_for_update()
    t = session.execute(q).scalar_one_or_none()
    if t is None:
        raise NotFound("thread not found")
    return t


def thread_messages(session: Session, thread: AssistantThread) -> list[AssistantMessage]:
    return list(
        session.execute(
            select(AssistantMessage)
            .where(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at, AssistantMessage.id)
        ).scalars()
    )


def post_message(
    session: Session,
    org: Organization,
    thread: AssistantThread,
    content: str,
    user_id: str | None,
    locale: str = "en",
) -> tuple[AssistantMessage, AssistantMessage]:
    reply, plan, model_version = think(session, org, thread, content, locale)
    now = utcnow()
    user_msg = AssistantMessage(
        org_id=org.id,
        thread_id=thread.id,
        role="user",
        content=content,
        plan=None,
        applied=[],
        results={},
        created_by=user_id,
        created_at=now,
    )
    bot = AssistantMessage(
        org_id=org.id,
        thread_id=thread.id,
        role="assistant",
        content=reply,
        plan=plan,
        applied=[],
        results={},
        model_version=model_version[:120],
        created_at=now + timedelta(microseconds=1),
    )
    session.add_all([user_msg, bot])
    if not thread.title:
        thread.title = " ".join(content.split())[:80]
    thread.updated_at = now
    session.flush()
    return user_msg, bot


# --------------------------------------------------------------------------- apply


def _resolve(kind: str, data: dict[str, Any], results: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    out = dict(data)
    for key in REF_FIELDS.get(kind, {}):
        val = out.get(key)
        if not (isinstance(val, str) and (m := REF.match(val))):
            continue
        ref = m.group(1)
        created = (results.get(ref) or {}).get("id")
        if created:
            out[key] = created
        elif key in REQUIRED_REFS:
            raise Conflict(f"apply action {ref} first: {key} refers to it")
        else:
            out.pop(key)
            warnings.append(f"{key} not linked: action {ref} has not been applied")
    return out


def _exec(
    session: Session,
    org: Organization,
    user_id: str | None,
    kind: str,
    data: dict[str, Any],
    extra: dict[str, Any],
) -> tuple[str, str | None]:
    """Run one action through the services. Returns (id, note); `extra` gets one-time values."""
    if kind == "update_org":
        update_org(org, OrgData.model_validate(data).model_dump(exclude_none=True))
        session.flush()
        return org.id, None
    if kind == "create_workflow":
        body = WorkflowIn.model_validate(data)
        existing = wfl.find_by_name(session, org.id, body.name)
        if existing is not None:
            return existing.id, "a workflow with this name already existed"
        return wfl.create_workflow(session, org, body).id, None
    if kind == "create_price_list":
        body_pl = PriceListIn.model_validate(data)
        existing_pl = pricelists.find_by_name(session, org.id, body_pl.name)
        if existing_pl is not None:
            return existing_pl.id, "a price list with this name already existed"
        return pricelists.create_price_list(session, org.id, body_pl).id, None
    if kind == "create_account":
        body_acc = AccountIn.model_validate(data)
        acc = crm.find_account_by_name(session, org.id, body_acc.name)
        if acc is not None:
            # fill links the existing account does not have yet; never overwrite
            if body_acc.price_list_id and not acc.price_list_id:
                acc.price_list_id = body_acc.price_list_id
            if body_acc.workflow_template_id and not acc.workflow_template_id:
                acc.workflow_template_id = body_acc.workflow_template_id
            session.flush()
            return acc.id, "an account with this name already existed"
        return crm.create_account(session, org, body_acc, user_id).id, None
    if kind == "create_contact":
        body_c = ContactData.model_validate(data)
        acc = crm.get_account(session, org.id, body_c.account_id)
        same = session.execute(
            select(CrmContact).where(
                CrmContact.org_id == org.id,
                CrmContact.account_id == acc.id,
                func.lower(CrmContact.email) == str(body_c.email).lower()
                if body_c.email
                else func.lower(CrmContact.name) == body_c.name.lower(),
            )
        ).scalar_one_or_none()
        if same is not None:
            return same.id, "this contact already existed"
        contact = ContactIn.model_validate(body_c.model_dump(exclude={"account_id"}))
        return crm.create_contact(session, org.id, acc, contact).id, None
    if kind == "create_deal":
        return crm.create_deal(session, org.id, DealIn.model_validate(data), user_id).id, None
    if kind == "create_activity":
        return crm.create_activity(session, org.id, ActivityIn.model_validate(data), user_id).id, None
    if kind == "create_dashboard":
        body_d = DashboardIn.model_validate(data)
        existing_d = dashboards.find_by_name(session, org.id, body_d.name)
        if existing_d is not None:
            return existing_d.id, "a dashboard with this name already existed"
        return dashboards.create_dashboard(session, org.id, body_d, user_id).id, None
    if kind == "create_glossary":
        body_g = GlossaryData.model_validate(data)
        g = (
            session.execute(
                select(Glossary).where(
                    Glossary.org_id == org.id, func.lower(Glossary.name) == body_g.name.lower()
                )
            )
            .scalars()
            .first()
        )
        if g is not None:
            return g.id, "a glossary with this name already existed"
        return gl.create_glossary(session, org.id, body_g.name, body_g.content_type or None).id, None
    if kind == "add_terms":
        body_t = TermsData.model_validate(data)
        g = session.get(Glossary, body_t.glossary_id)
        if g is None or g.org_id != org.id:
            raise NotFound("glossary not found")
        for term in body_t.terms:
            gl.add_term(
                session,
                g.id,
                term.source_lang,
                term.target_lang,
                term.source_term,
                term.target_term,
                term.kind,
                note=term.note,
            )
        return g.id, f"{len(body_t.terms)} term(s) added"
    if kind == "create_webhook":
        import secrets

        body_w = WebhookData.model_validate(data)
        bad = [e for e in body_w.events if e not in webhooks.EVENTS]
        if bad:
            raise Invalid(f"unknown webhook event(s): {', '.join(bad)}")
        h = Webhook(
            org_id=org.id,
            url=webhooks.check_url(body_w.url),
            secret=secrets.token_hex(24),
            events=list(dict.fromkeys(body_w.events)),
        )
        session.add(h)
        session.flush()
        extra["secret"] = h.secret  # shown once, in this apply response only (like POST /webhooks)
        return h.id, None
    raise Invalid(f"unknown action type {kind}")


def apply(
    session: Session,
    org: Organization,
    msg: AssistantMessage,
    indices: list[int] | None,
    user_id: str | None,
) -> list[dict[str, Any]]:
    """Execute the selected actions in order; one savepoint per action. Idempotent per index."""
    if msg.role != "assistant" or msg.plan is None:
        raise Conflict("only an assistant message with a plan can be applied")
    plan = list(msg.plan)
    wanted = list(range(len(plan))) if indices is None else sorted(set(indices))
    bad = [i for i in wanted if i < 0 or i >= len(plan)]
    if bad:
        raise Invalid(f"no action with index {', '.join(map(str, bad))} in this plan", {"actions": len(plan)})
    applied = set(msg.applied or [])
    results: dict[str, Any] = {k: dict(v) for k, v in (msg.results or {}).items()}
    out: list[dict[str, Any]] = []
    for i in wanted:
        act = plan[i]
        kind = str(act.get("type"))
        if i in applied:
            out.append(
                {
                    "index": i,
                    "type": kind,
                    "ok": True,
                    "id": results.get(str(i), {}).get("id"),
                    "skipped": True,
                }
            )
            continue
        warnings: list[str] = []
        extra: dict[str, Any] = {}
        try:
            with session.begin_nested():
                data = _resolve(kind, dict(act.get("data") or {}), results, warnings)
                obj_id, note = _exec(session, org, user_id, kind, data, extra)
        except (ServiceError, ValidationError, ValueError, SQLAlchemyError) as e:
            out.append({"index": i, "type": kind, "ok": False, "error": _short_error(e)})
            continue
        applied.add(i)
        results[str(i)] = {"id": obj_id}
        row: dict[str, Any] = {"index": i, "type": kind, "ok": True, "id": obj_id}
        if note:
            row["note"] = note
        if warnings:
            row["warnings"] = warnings
        row.update(extra)
        out.append(row)
    msg.applied = sorted(applied)
    msg.results = results
    session.flush()
    return out

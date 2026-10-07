"""Dashboards: widget validation, metric computation (SQL aggregates), the default dashboard.

Definitions (period = last 30, 90 or 365 days; every query scoped by org):
  revenue           sum of job revenue for jobs delivered in the period (recognised at delivery)
  margin            that revenue minus engine and reviewer cost of the same jobs
  margin_pct        margin / revenue * 100 (null without revenue)
  jobs_active       jobs now in running | review | ready | merging (not period bound)
  jobs_overdue      jobs past due_at and not delivered, settled or cancelled (now)
  auto_rate         auto-approved segments / segments, jobs created in the period
  escaped_rate      accepted escaped errors on auto-approved segments / auto-approved segments
  open_deals_value  sum of deal values not won or lost (now), with a per-currency split
  words_delivered   words of jobs delivered in the period
  reviewer_cost     reviewer pay of review tasks submitted in the period (accepted or payable)
Series group by calendar month (UTC). Rates are null when there is nothing to divide by:
no data is not a 0% rate. Money is a decimal string; the client role sees money as null.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from arbiter.agency.common import iso, money
from arbiter.agency.crm import ACTIVE_JOB_STATES, DEAL_STAGES, DELIVERED_JOB_STATES
from arbiter.agency.schemas import DashboardIn, DashboardPatch, WidgetIn
from arbiter.config import get_settings
from arbiter.errors import Invalid, NotFound
from arbiter.models import (
    CrmAccount,
    CrmActivity,
    CrmDeal,
    Dashboard,
    EscapedError,
    FileAsset,
    Job,
    Project,
    ReviewTask,
    utcnow,
)

METRICS: dict[str, tuple[str, ...]] = {
    "kpi": (
        "revenue",
        "margin",
        "margin_pct",
        "jobs_active",
        "jobs_overdue",
        "auto_rate",
        "escaped_rate",
        "open_deals_value",
        "words_delivered",
        "reviewer_cost",
    ),
    "bar": ("revenue_by_month", "jobs_by_state", "revenue_by_account", "words_by_pair", "auto_rate_by_month"),
    "line": (
        "revenue_by_month",
        "jobs_by_state",
        "revenue_by_account",
        "words_by_pair",
        "auto_rate_by_month",
    ),
    "pipeline": ("deals_by_stage",),
    "table": ("overdue_jobs", "top_accounts", "open_activities", "recent_deliveries"),
}
TITLES: dict[str, str] = {
    "revenue": "Revenue",
    "margin": "Margin",
    "margin_pct": "Margin %",
    "jobs_active": "Active jobs",
    "jobs_overdue": "Overdue jobs",
    "auto_rate": "Auto-approval rate",
    "escaped_rate": "Escaped error rate",
    "open_deals_value": "Open deals",
    "words_delivered": "Words delivered",
    "reviewer_cost": "Reviewer cost",
    "revenue_by_month": "Revenue by month",
    "jobs_by_state": "Jobs by state",
    "revenue_by_account": "Revenue by account",
    "words_by_pair": "Words by language pair",
    "auto_rate_by_month": "Auto-approval rate by month",
    "deals_by_stage": "Deal pipeline",
    "overdue_jobs": "Overdue jobs",
    "top_accounts": "Top accounts",
    "open_activities": "Open activities",
    "recent_deliveries": "Recent deliveries",
}
PERIODS = {"30d": 30, "90d": 90, "365d": 365}
FINAL_JOB_STATES = ("delivered", "settled", "cancelled", "disputed")
TABLE_LIMIT = 20

DEFAULT_WIDGETS: list[tuple[str, str, str]] = [
    ("kpi", "revenue", "s"),
    ("kpi", "margin_pct", "s"),
    ("kpi", "jobs_active", "s"),
    ("kpi", "jobs_overdue", "s"),
    ("kpi", "auto_rate", "s"),
    ("kpi", "open_deals_value", "s"),
    ("line", "revenue_by_month", "l"),
    ("bar", "jobs_by_state", "m"),
    ("pipeline", "deals_by_stage", "m"),
    ("table", "overdue_jobs", "l"),
    ("table", "open_activities", "m"),
]


# --------------------------------------------------------------------------- CRUD


def validate_widgets(widgets: list[WidgetIn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    for i, w in enumerate(widgets):
        allowed = METRICS[w.type]
        if w.metric not in allowed:
            raise Invalid(
                f"widget {i}: metric {w.metric!r} is not available for type {w.type}",
                {"index": i, "allowed": list(allowed)},
            )
        wid = w.id or f"w{i + 1}"
        while wid in ids:
            wid = f"{wid}_{i + 1}"
        ids.add(wid)
        out.append(
            {
                "id": wid,
                "type": w.type,
                "metric": w.metric,
                "title": w.title or TITLES[w.metric],
                "size": w.size,
            }
        )
    return out


def get_dashboard(session: Session, org_id: str, dash_id: str) -> Dashboard:
    d = session.execute(
        select(Dashboard).where(Dashboard.id == dash_id, Dashboard.org_id == org_id)
    ).scalar_one_or_none()
    if d is None:
        raise NotFound("dashboard not found")
    return d


def find_by_name(session: Session, org_id: str, name: str) -> Dashboard | None:
    return (
        session.execute(
            select(Dashboard).where(
                Dashboard.org_id == org_id, func.lower(Dashboard.name) == name.strip().lower()
            )
        )
        .scalars()
        .first()
    )


def create_dashboard(
    session: Session, org_id: str, body: DashboardIn, user_id: str | None = None
) -> Dashboard:
    d = Dashboard(org_id=org_id, name=body.name, widgets=validate_widgets(body.widgets), created_by=user_id)
    session.add(d)
    session.flush()
    return d


def update_dashboard(session: Session, d: Dashboard, body: DashboardPatch) -> Dashboard:
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        if not data["name"]:
            raise Invalid("name cannot be empty")
        d.name = data["name"]
    if "widgets" in data:
        d.widgets = validate_widgets(body.widgets or [])
    d.updated_at = utcnow()
    session.flush()
    return d


def default_dashboard(session: Session, org_id: str, user_id: str | None = None) -> Dashboard:
    """GET /dashboards/default: the org's default dashboard, created on first call."""
    d = (
        session.execute(
            select(Dashboard)
            .where(Dashboard.org_id == org_id, Dashboard.is_default.is_(True))
            .order_by(Dashboard.created_at)
        )
        .scalars()
        .first()
    )
    if d is not None:
        return d
    widgets = [WidgetIn(type=t, metric=m, size=s) for t, m, s in DEFAULT_WIDGETS]  # type: ignore[arg-type]
    d = Dashboard(
        org_id=org_id, name="Overview", widgets=validate_widgets(widgets), is_default=True, created_by=user_id
    )
    session.add(d)
    session.flush()
    return d


def dashboard_view(d: Dashboard) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "widgets": [dict(w) for w in (d.widgets or [])],
        "is_default": d.is_default,
        "created_at": iso(d.created_at),
        "updated_at": iso(d.updated_at),
    }


# --------------------------------------------------------------------------- metrics


class _Ctx:
    def __init__(self, session: Session, org_id: str, days: int, hide_money: bool) -> None:
        self.s = session
        self.org_id = org_id
        self.now = utcnow()
        self.since = self.now - timedelta(days=days)
        self.prev_since = self.since - timedelta(days=days)
        self.hide_money = hide_money
        self.currency = get_settings().currency

    def m(self, value: Decimal | int | str | None) -> str | None:
        return None if self.hide_money else money(value)


ZERO = Decimal("0")


def _revenue_cost(c: _Ctx, start: Any, end: Any) -> tuple[Decimal, Decimal]:
    rev, cost = c.s.execute(
        select(
            func.coalesce(func.sum(Job.revenue), ZERO),
            func.coalesce(func.sum(Job.cost_engines + Job.cost_reviewers), ZERO),
        ).where(
            Job.org_id == c.org_id,
            Job.state.in_(DELIVERED_JOB_STATES),
            Job.delivered_at >= start,
            Job.delivered_at < end,
        )
    ).one()
    return Decimal(rev), Decimal(cost)


def _kpi(value: Any, unit: str, previous: Any = None) -> dict[str, Any]:
    return {"value": value, "unit": unit, "previous": previous}


def _pct(num: Decimal | int, den: Decimal | int) -> float | None:
    return round(float(Decimal(num) / Decimal(den)) * 100, 2) if den else None


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _auto(c: _Ctx, start: Any, end: Any) -> tuple[int, int]:
    auto, total = c.s.execute(
        select(
            func.coalesce(func.sum(Job.auto_approved_count), 0), func.coalesce(func.sum(Job.segment_count), 0)
        ).where(Job.org_id == c.org_id, Job.created_at >= start, Job.created_at < end, Job.segment_count > 0)
    ).one()
    return int(auto), int(total)


def _escaped(c: _Ctx, start: Any, end: Any) -> int:
    return int(
        c.s.execute(
            select(func.count())
            .select_from(EscapedError)
            .where(
                EscapedError.org_id == c.org_id,
                EscapedError.created_at >= start,
                EscapedError.created_at < end,
                EscapedError.was_auto_approved.is_(True),
                EscapedError.accepted.is_(True),
            )
        ).scalar_one()
    )


def _overdue_filter(c: _Ctx) -> list[Any]:
    return [
        Job.org_id == c.org_id,
        Job.due_at.is_not(None),
        Job.due_at < c.now,
        Job.state.not_in(FINAL_JOB_STATES),
    ]


def kpi(c: _Ctx, metric: str) -> dict[str, Any]:
    if metric in ("revenue", "margin", "margin_pct"):
        rev, cost = _revenue_cost(c, c.since, c.now)
        prev_rev, prev_cost = _revenue_cost(c, c.prev_since, c.since)
        if metric == "revenue":
            return _kpi(c.m(rev), c.currency, c.m(prev_rev))
        if metric == "margin":
            return _kpi(c.m(rev - cost), c.currency, c.m(prev_rev - prev_cost))
        if c.hide_money:
            return _kpi(None, "%")
        return _kpi(_pct(rev - cost, rev), "%", _pct(prev_rev - prev_cost, prev_rev))
    if metric == "jobs_active":
        n = c.s.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.org_id == c.org_id, Job.state.in_(ACTIVE_JOB_STATES))
        ).scalar_one()
        return _kpi(int(n), "jobs")
    if metric == "jobs_overdue":
        n = c.s.execute(select(func.count()).select_from(Job).where(*_overdue_filter(c))).scalar_one()
        return _kpi(int(n), "jobs")
    if metric == "auto_rate":
        a, t = _auto(c, c.since, c.now)
        pa, pt = _auto(c, c.prev_since, c.since)
        return _kpi(_rate(a, t), "ratio", _rate(pa, pt))
    if metric == "escaped_rate":
        a, _ = _auto(c, c.since, c.now)
        pa, _ = _auto(c, c.prev_since, c.since)
        return _kpi(
            _rate(_escaped(c, c.since, c.now), a), "ratio", _rate(_escaped(c, c.prev_since, c.since), pa)
        )
    if metric == "open_deals_value":
        rows = c.s.execute(
            select(CrmDeal.currency, func.coalesce(func.sum(CrmDeal.value), ZERO), func.count())
            .where(CrmDeal.org_id == c.org_id, CrmDeal.stage.not_in(("won", "lost")))
            .group_by(CrmDeal.currency)
        ).all()
        by_cur = {cur: Decimal(v) for cur, v, _ in rows}
        out = _kpi(c.m(by_cur.get(c.currency, ZERO)), c.currency)
        out["count"] = sum(int(n) for _, _, n in rows)
        out["by_currency"] = {cur: c.m(v) for cur, v in sorted(by_cur.items())}
        return out
    if metric == "words_delivered":

        def words(start: Any, end: Any) -> int:
            return int(
                c.s.execute(
                    select(func.coalesce(func.sum(Job.word_count), 0)).where(
                        Job.org_id == c.org_id,
                        Job.state.in_(DELIVERED_JOB_STATES),
                        Job.delivered_at >= start,
                        Job.delivered_at < end,
                    )
                ).scalar_one()
            )

        return _kpi(words(c.since, c.now), "words", words(c.prev_since, c.since))
    if metric == "reviewer_cost":

        def cost(start: Any, end: Any) -> Decimal:
            return Decimal(
                c.s.execute(
                    select(func.coalesce(func.sum(ReviewTask.pay_amount), ZERO))
                    .join(Job, Job.id == ReviewTask.job_id)
                    .where(
                        Job.org_id == c.org_id,
                        ReviewTask.state.in_(("accepted", "payable")),
                        ReviewTask.submitted_at >= start,
                        ReviewTask.submitted_at < end,
                    )
                ).scalar_one()
            )

        return _kpi(c.m(cost(c.since, c.now)), c.currency, c.m(cost(c.prev_since, c.since)))
    raise Invalid(f"unknown kpi metric {metric}")


def _month(col: Any) -> Any:
    """YYYY-MM in UTC. Literal arguments (not bind parameters) so Postgres can match the
    SELECT expression with the GROUP BY expression."""
    return func.to_char(func.timezone(literal_column("'UTC'"), col), literal_column("'YYYY-MM'"))


def _months(c: _Ctx) -> list[str]:
    """Every calendar month touched by the period, oldest first (so empty months show as 0)."""
    out: list[str] = []
    y, m = c.since.year, c.since.month
    while (y, m) <= (c.now.year, c.now.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def series(c: _Ctx, metric: str) -> dict[str, Any]:
    if metric == "revenue_by_month":
        month = _month(Job.delivered_at)
        rows = dict(
            c.s.execute(
                select(month, func.coalesce(func.sum(Job.revenue), ZERO))
                .where(
                    Job.org_id == c.org_id,
                    Job.state.in_(DELIVERED_JOB_STATES),
                    Job.delivered_at >= c.since,
                )
                .group_by(month)
            ).all()
        )
        points = [{"label": mo, "value": c.m(rows.get(mo, ZERO))} for mo in _months(c)]
        return {"unit": c.currency, "points": points}
    if metric == "auto_rate_by_month":
        month = _month(Job.created_at)
        rows = {
            mo: (int(a), int(t))
            for mo, a, t in c.s.execute(
                select(
                    month,
                    func.coalesce(func.sum(Job.auto_approved_count), 0),
                    func.coalesce(func.sum(Job.segment_count), 0),
                )
                .where(Job.org_id == c.org_id, Job.created_at >= c.since, Job.segment_count > 0)
                .group_by(month)
            ).all()
        }
        points = [{"label": mo, "value": _rate(*rows.get(mo, (0, 0)))} for mo in _months(c)]
        return {"unit": "ratio", "points": points}
    if metric == "jobs_by_state":
        rows = c.s.execute(
            select(Job.state, func.count())
            .where(Job.org_id == c.org_id, Job.created_at >= c.since)
            .group_by(Job.state)
            .order_by(func.count().desc(), Job.state)
        ).all()
        return {"unit": "jobs", "points": [{"label": st, "value": int(n)} for st, n in rows]}
    if metric == "revenue_by_account":
        rows = c.s.execute(
            select(Job.account_id, CrmAccount.name, func.coalesce(func.sum(Job.revenue), ZERO).label("rev"))
            .outerjoin(CrmAccount, CrmAccount.id == Job.account_id)
            .where(Job.org_id == c.org_id, Job.state.in_(DELIVERED_JOB_STATES), Job.delivered_at >= c.since)
            .group_by(Job.account_id, CrmAccount.name)
            .order_by(func.sum(Job.revenue).desc())
            .limit(10)
        ).all()
        points = [{"label": name or "No account", "id": aid, "value": c.m(rev)} for aid, name, rev in rows]
        return {"unit": c.currency, "points": points}
    if metric == "words_by_pair":
        rows = c.s.execute(
            select(Job.source_lang, Job.target_lang, func.coalesce(func.sum(Job.word_count), 0))
            .where(Job.org_id == c.org_id, Job.created_at >= c.since, Job.state != "cancelled")
            .group_by(Job.source_lang, Job.target_lang)
            .order_by(func.sum(Job.word_count).desc())
        ).all()
        return {"unit": "words", "points": [{"label": f"{s}-{t}", "value": int(n)} for s, t, n in rows]}
    raise Invalid(f"unknown series metric {metric}")


def pipeline(c: _Ctx) -> dict[str, Any]:
    rows = {
        st: (int(n), Decimal(v))
        for st, n, v in c.s.execute(
            select(CrmDeal.stage, func.count(), func.coalesce(func.sum(CrmDeal.value), ZERO))
            .where(CrmDeal.org_id == c.org_id)
            .group_by(CrmDeal.stage)
        ).all()
    }
    return {
        "currency": c.currency,
        "stages": [
            {"stage": st, "count": rows.get(st, (0, ZERO))[0], "value": c.m(rows.get(st, (0, ZERO))[1])}
            for st in DEAL_STAGES
        ],
    }


def table(c: _Ctx, metric: str) -> dict[str, Any]:
    if metric == "overdue_jobs":
        rows = c.s.execute(
            select(Job, Project.name, CrmAccount.name)
            .join(Project, Project.id == Job.project_id)
            .outerjoin(CrmAccount, CrmAccount.id == Job.account_id)
            .where(*_overdue_filter(c))
            .order_by(Job.due_at, Job.id)
            .limit(TABLE_LIMIT)
        ).all()
        cols = ["job_id", "project", "account", "target_lang", "state", "due_at", "hours_overdue"]
        out = [
            {
                "job_id": j.id,
                "project": pname,
                "account": aname,
                "target_lang": j.target_lang,
                "state": j.state,
                "due_at": iso(j.due_at),
                "hours_overdue": round((c.now - j.due_at).total_seconds() / 3600, 1),
            }
            for j, pname, aname in rows
        ]
        return {"columns": cols, "rows": out}
    if metric == "top_accounts":
        rows = c.s.execute(
            select(
                CrmAccount.id,
                CrmAccount.name,
                func.coalesce(func.sum(Job.revenue), ZERO),
                func.coalesce(func.sum(Job.cost_engines + Job.cost_reviewers), ZERO),
                func.count(Job.id),
            )
            .join(Job, Job.account_id == CrmAccount.id)
            .where(
                CrmAccount.org_id == c.org_id,
                Job.org_id == c.org_id,
                Job.state.in_(DELIVERED_JOB_STATES),
                Job.delivered_at >= c.since,
            )
            .group_by(CrmAccount.id, CrmAccount.name)
            .order_by(func.sum(Job.revenue).desc(), CrmAccount.name)
            .limit(10)
        ).all()
        cols = ["account_id", "name", "revenue", "margin", "jobs"]
        out = [
            {
                "account_id": aid,
                "name": name,
                "revenue": c.m(rev),
                "margin": c.m(Decimal(rev) - Decimal(cost)),
                "jobs": int(n),
            }
            for aid, name, rev, cost, n in rows
        ]
        return {"columns": cols, "rows": out}
    if metric == "open_activities":
        rows = c.s.execute(
            select(CrmActivity, CrmAccount.name)
            .join(CrmAccount, CrmAccount.id == CrmActivity.account_id)
            .where(CrmActivity.org_id == c.org_id, CrmActivity.done.is_(False))
            .order_by(CrmActivity.due_at.asc().nulls_last(), CrmActivity.created_at)
            .limit(TABLE_LIMIT)
        ).all()
        cols = ["id", "account", "kind", "body", "due_at", "overdue"]
        out = [
            {
                "id": a.id,
                "account_id": a.account_id,
                "account": aname,
                "kind": a.kind,
                "body": a.body[:200],
                "due_at": iso(a.due_at),
                "overdue": bool(a.due_at and a.due_at < c.now),
            }
            for a, aname in rows
        ]
        return {"columns": cols, "rows": out}
    if metric == "recent_deliveries":
        rows = c.s.execute(
            select(Job, Project.name, FileAsset.filename)
            .join(Project, Project.id == Job.project_id)
            .join(FileAsset, FileAsset.id == Job.file_id)
            .where(Job.org_id == c.org_id, Job.state.in_(DELIVERED_JOB_STATES), Job.delivered_at >= c.since)
            .order_by(Job.delivered_at.desc(), Job.id)
            .limit(TABLE_LIMIT)
        ).all()
        cols = ["job_id", "project", "filename", "target_lang", "words", "delivered_at", "revenue"]
        out = [
            {
                "job_id": j.id,
                "project": pname,
                "filename": fname,
                "target_lang": j.target_lang,
                "words": j.word_count,
                "delivered_at": iso(j.delivered_at),
                "revenue": c.m(j.revenue),
            }
            for j, pname, fname in rows
        ]
        return {"columns": cols, "rows": out}
    raise Invalid(f"unknown table metric {metric}")


def widget_data(c: _Ctx, w: dict[str, Any]) -> Any:
    t, metric = w.get("type"), str(w.get("metric"))
    if t == "kpi":
        return kpi(c, metric)
    if t in ("bar", "line"):
        return series(c, metric)
    if t == "pipeline":
        return pipeline(c)
    if t == "table":
        return table(c, metric)
    raise Invalid(f"unknown widget type {t}")


def dashboard_data(
    session: Session, org_id: str, d: Dashboard, period: str, *, hide_money: bool
) -> dict[str, Any]:
    if period not in PERIODS:
        raise Invalid("period must be one of 30d, 90d, 365d")
    c = _Ctx(session, org_id, PERIODS[period], hide_money)
    out = []
    for w in d.widgets or []:
        out.append(
            {"id": w.get("id"), "type": w.get("type"), "title": w.get("title"), "data": widget_data(c, w)}
        )
    return {"period": period, "currency": c.currency, "generated_at": iso(c.now), "widgets": out}


def compute_metric(session: Session, org_id: str, widget_type: str, metric: str, period: str = "30d") -> Any:
    """One metric outside a dashboard (used by the assistant's context summary)."""
    c = _Ctx(session, org_id, PERIODS[period], False)
    return widget_data(c, {"type": widget_type, "metric": metric})

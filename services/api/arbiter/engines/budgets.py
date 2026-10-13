"""Monthly cost caps per org and provider (engine_budgets).

check()  before a call: raises BudgetExceeded when the current month's spend has reached
         the cap. The router also drops capped providers up front, so a job that can use
         another engine keeps running.
charge() after a call: one atomic UPDATE adds the cost (or restarts the month), so
         concurrent workers never lose an increment.

Budgeted wrappers enforce both around any LlmClient / MtEngine handed to the pipeline.
Spend is an estimate (pricing.py); the provider bill is the truth.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from arbiter.contracts import EngineError, LlmClient, MtEngine, MtRequest, MtResult, Usage
from arbiter.engines.errors import BudgetExceeded
from arbiter.models import EngineBudget, utcnow


def current_period(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%Y-%m")


def get(session: Session, org_id: str, provider: str) -> EngineBudget | None:
    return session.execute(
        select(EngineBudget).where(EngineBudget.org_id == org_id, EngineBudget.provider == provider)
    ).scalar_one_or_none()


def spent_this_month(b: EngineBudget, now: datetime | None = None) -> Decimal:
    return Decimal(b.spent or 0) if b.period == current_period(now) else Decimal("0")


def exceeded(session: Session, org_id: str | None, provider: str) -> bool:
    if not org_id or provider == "mock":
        return False
    b = get(session, org_id, provider)
    if b is None or not b.enabled:
        return False
    return spent_this_month(b) >= Decimal(b.monthly_cap)


def check(session: Session, org_id: str | None, provider: str) -> None:
    if exceeded(session, org_id, provider):
        raise BudgetExceeded([provider])


def charge(session: Session, org_id: str | None, provider: str, cost: Decimal) -> None:
    if not org_id or not cost or provider == "mock":
        return
    period = current_period()
    session.execute(
        update(EngineBudget)
        .where(EngineBudget.org_id == org_id, EngineBudget.provider == provider)
        .values(
            spent=case((EngineBudget.period == period, EngineBudget.spent + cost), else_=cost),
            period=period,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    # keep any loaded instance in step with the row
    b = session.execute(
        select(EngineBudget).where(EngineBudget.org_id == org_id, EngineBudget.provider == provider)
    ).scalar_one_or_none()
    if b is not None:
        session.refresh(b)


class BudgetedLlm:
    """LlmClient proxy: cap checked before, spend charged after every call."""

    def __init__(self, inner: LlmClient, session: Session, org_id: str | None, provider: str) -> None:
        self.inner = inner
        self.session = session
        self.org_id = org_id
        self.provider = provider
        self.name = inner.name
        self.region = getattr(inner, "region", "global")

    def available(self) -> bool:
        return self.inner.available()

    def complete_json(self, system: str, user: str, **kw: Any) -> tuple[dict[str, Any], Usage, str]:
        check(self.session, self.org_id, self.provider)
        data, usage, model = self.inner.complete_json(system, user, **kw)
        charge(self.session, self.org_id, self.provider, usage.cost)
        return data, usage, model


class BudgetedMt:
    def __init__(self, inner: MtEngine, session: Session, org_id: str | None, provider: str) -> None:
        self.inner = inner
        self.session = session
        self.org_id = org_id
        self.provider = provider
        self.name = inner.name
        self.region = getattr(inner, "region", "global")
        self.supports_glossary = inner.supports_glossary

    def available(self) -> bool:
        return self.inner.available()

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        check(self.session, self.org_id, self.provider)
        results = self.inner.translate(requests)
        charge(self.session, self.org_id, self.provider, sum((r.usage.cost for r in results), Decimal("0")))
        return results


class FailoverLlm:
    """Ordered LLM clients: the next one answers when the previous raises EngineError.
    A BudgetExceeded on one provider moves on too; when every client fails the last
    error is raised (the caller then routes to a human, as for any judge failure)."""

    def __init__(self, clients: list[LlmClient]) -> None:
        if not clients:
            raise EngineError("no LLM available")
        self.clients = clients
        self.name = clients[0].name
        self.region = getattr(clients[0], "region", "global")

    def available(self) -> bool:
        return any(c.available() for c in self.clients)

    def complete_json(self, system: str, user: str, **kw: Any) -> tuple[dict[str, Any], Usage, str]:
        last: EngineError | None = None
        for c in self.clients:
            try:
                return c.complete_json(system, user, **kw)
            except EngineError as e:
                last = e
        assert last is not None
        raise last

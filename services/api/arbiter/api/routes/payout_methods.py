"""Reviewer payout method setup per rail: Payoneer onboarding, PayPal, SEPA, Wise (D-052)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from arbiter.api.deps import DB, Reviewer
from arbiter.community import payout_accounts

router = APIRouter(tags=["reviewers"])

Method = Literal["payoneer", "paypal", "sepa", "wise"]


@router.get("/reviewer/payout-methods")
def payout_methods(profile: Reviewer, db: DB) -> dict[str, Any]:
    return payout_accounts.methods_view(db, profile)


class AccountIn(BaseModel):
    method: Method
    details: dict[str, str] = Field(default_factory=dict, max_length=10)


@router.post("/reviewer/payout-accounts")
def setup_account(body: AccountIn, profile: Reviewer, db: DB) -> dict[str, Any]:
    return payout_accounts.setup(db, profile, body.method, body.details)


@router.post("/reviewer/payout-accounts/{method}/refresh")
def refresh_account(method: Method, profile: Reviewer, db: DB) -> dict[str, Any]:
    return payout_accounts.refresh(db, profile, method)

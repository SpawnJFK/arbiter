"""Reviewer community endpoints: apply, profile, qualification tests, tasks, earnings, disputes.

Access rules:
  * /reviewers/apply is public and returns a session token for the new reviewer.
  * every /reviewer/* endpoint needs a reviewer token (customers and admins get 403).
  * tests are open while the profile is applied or active (pairs in "testing"); a suspended
    or banned reviewer cannot take tests.
  * tasks (next, submit, release) need profile status "active"; anything else is 403 with
    the reason in the message.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from arbiter.api import security
from arbiter.api.deps import DB, Paging, Reviewer, listing
from arbiter.api.routes.auth import user_view
from arbiter.community import disputes, payouts, profiles, queue, review, testing
from arbiter.errors import Forbidden
from arbiter.models import ReviewerProfile

router = APIRouter(tags=["reviewers"])


def _require_active(profile: ReviewerProfile) -> None:
    if profile.status != "active":
        if profile.status == "applied":
            msg = "your reviewer account is not active yet: pass the qualification tests for a language pair"
        else:
            msg = f"your reviewer account is {profile.status}; review tasks are not available"
        raise Forbidden(msg, {"status": profile.status})


def _require_can_test(profile: ReviewerProfile) -> None:
    if profile.status not in ("applied", "active"):
        raise Forbidden(
            f"your reviewer account is {profile.status}; tests are not available", {"status": profile.status}
        )


# ------------------------------------------------------------------ apply + profile


class PairIn(BaseModel):
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)


class ApplyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Plain str: profiles.apply validates the format. EmailStr rejects reserved domains (.test).
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    pairs: list[PairIn] = Field(min_length=1, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=20)


@router.post("/reviewers/apply", status_code=201)
def apply(body: ApplyIn, db: DB) -> dict[str, Any]:
    user, profile = profiles.apply(
        db,
        name=body.name,
        email=str(body.email),
        password=body.password,
        country=body.country,
        pairs=[p.model_dump() for p in body.pairs],
        domains=body.domains,
    )
    return {
        "token": security.issue_token(user.id, user.role, None),
        "user": user_view(user),
        "profile": profiles.profile_view(db, profile),
    }


@router.get("/reviewer/me")
def get_me(profile: Reviewer, db: DB) -> dict[str, Any]:
    return profiles.profile_view(db, profile)


class ProfilePatch(BaseModel):
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    date_of_birth: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    payout_method: Literal["wise", "paypal", "sepa"] | None = None
    payout_details: dict[str, Any] | None = None


@router.patch("/reviewer/me")
def patch_me(body: ProfilePatch, profile: Reviewer, db: DB) -> dict[str, Any]:
    return profiles.update_tax_info(db, profile, **body.model_dump(exclude_none=True))


# ------------------------------------------------------------------ qualification tests


@router.get("/reviewer/tests")
def list_tests(profile: Reviewer, db: DB, pg: Paging) -> dict[str, Any]:
    items = testing.available_tests(db, profile)
    return listing(items[pg.offset : pg.offset + pg.limit + 1], pg)


@router.post("/reviewer/tests/{test_id}/start")
def start_test(test_id: str, profile: Reviewer, db: DB) -> dict[str, Any]:
    _require_can_test(profile)
    return testing.start(db, profile, test_id)


class TestErrorIn(BaseModel):
    span: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=60)
    severity: str = Field(default="minor", max_length=20)


class AnswerIn(BaseModel):
    index: int = Field(ge=0)
    target: str | None = Field(default=None, max_length=20_000)
    errors: list[TestErrorIn] = Field(default_factory=list, max_length=50)


class AttemptSubmitIn(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list, max_length=500)


@router.post("/reviewer/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: str, body: AttemptSubmitIn, profile: Reviewer, db: DB) -> dict[str, Any]:
    _require_can_test(profile)
    answers = [a.model_dump(exclude_none=True) for a in body.answers]
    return testing.grade(db, profile, attempt_id, answers)


# ------------------------------------------------------------------ tasks


class NextIn(BaseModel):
    source_lang: str | None = Field(default=None, max_length=16)
    target_lang: str | None = Field(default=None, max_length=16)


@router.post("/reviewer/tasks/next", response_model=None)
def next_task(profile: Reviewer, db: DB, body: NextIn | None = None) -> dict[str, Any] | Response:
    _require_active(profile)
    body = body or NextIn()
    task = queue.next_task(db, profile, source_lang=body.source_lang, target_lang=body.target_lang)
    if task is None:
        return Response(status_code=204)
    return task


class ReviewErrorIn(BaseModel):
    dimension: str = Field(max_length=60)
    severity: str = Field(max_length=20)
    span: str = Field(default="", max_length=2000)
    explanation: str = Field(default="", max_length=2000)


class TaskSubmitIn(BaseModel):
    decision: Literal["accept", "edit", "escalate", "skip"]
    target_tagged: str | None = Field(default=None, max_length=50_000)
    errors: list[ReviewErrorIn] = Field(default_factory=list, max_length=50)
    comment: str = Field(default="", max_length=5000)
    time_ms: int = Field(default=0, ge=0)


@router.post("/reviewer/tasks/{task_id}/submit")
def submit_task(task_id: str, body: TaskSubmitIn, profile: Reviewer, db: DB) -> dict[str, Any]:
    _require_active(profile)
    return review.submit(
        db,
        profile,
        task_id,
        decision=body.decision,
        target_tagged=body.target_tagged,
        errors=[e.model_dump() for e in body.errors],
        comment=body.comment,
        time_ms=body.time_ms,
    )


@router.post("/reviewer/tasks/{task_id}/release", status_code=204)
def release_task(task_id: str, profile: Reviewer, db: DB) -> Response:
    _require_active(profile)
    queue.release(db, profile, task_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ money + disputes


@router.get("/reviewer/earnings")
def earnings(profile: Reviewer, db: DB) -> dict[str, Any]:
    return payouts.earnings_view(db, profile)


class DisputeIn(BaseModel):
    task_id: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=5000)


@router.post("/reviewer/disputes", status_code=201)
def open_dispute(body: DisputeIn, profile: Reviewer, db: DB) -> dict[str, Any]:
    if profile.status == "banned":
        raise Forbidden("your reviewer account is banned", {"status": profile.status})
    return disputes.open_dispute(db, profile, body.task_id, body.reason)

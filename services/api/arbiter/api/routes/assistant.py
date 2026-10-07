"""AI assistant (Agency OS). Roles: pm or API key.

The assistant proposes; a human applies. POST .../messages returns the user's message and
the assistant's answer with its plan; POST /assistant/messages/{id}/apply runs all or the
selected actions (indices) and is idempotent per index.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from arbiter.agency import assistant
from arbiter.api.deps import DB, PM, Paging, Principal, listing
from arbiter.api.routes.projects import idempotent_post
from arbiter.errors import NotFound
from arbiter.models import AssistantMessage, AssistantThread

router = APIRouter(tags=["assistant"])


def _uid(p: Principal) -> str | None:
    return p.user.id if p.user is not None else None


class ThreadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=20_000)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[int] | None = Field(default=None, max_length=200)


@router.post("/assistant/threads", status_code=201)
def create_thread(
    p: PM, db: DB, body: ThreadIn | None = None, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    body = body or ThreadIn()

    def make() -> dict[str, Any]:
        t = AssistantThread(org_id=p.org_id, title=(body.title or "").strip(), user_id=_uid(p))
        db.add(t)
        db.flush()
        return assistant.thread_view(t, [])

    return idempotent_post(db, p, "assistant.threads", idempotency_key, body.model_dump(mode="json"), make)


@router.get("/assistant/threads")
def list_threads(p: PM, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(AssistantThread)
            .where(AssistantThread.org_id == p.org_id)
            .order_by(AssistantThread.updated_at.desc(), AssistantThread.id.desc())
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([assistant.thread_view(t) for t in rows], pg)


@router.get("/assistant/threads/{thread_id}")
def get_thread(thread_id: str, p: PM, db: DB) -> dict[str, Any]:
    t = assistant.get_thread(db, p.org_id, thread_id)
    return assistant.thread_view(t, assistant.thread_messages(db, t))


@router.post("/assistant/threads/{thread_id}/messages", status_code=201)
def post_message(
    thread_id: str,
    body: MessageIn,
    p: PM,
    db: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    """Calls the model (or the built-in planner); nothing in the org changes here."""

    def make() -> dict[str, Any]:
        assert p.org is not None
        t = assistant.get_thread(db, p.org_id, thread_id, lock=True)
        user_msg, bot = assistant.post_message(db, p.org, t, body.content.strip(), _uid(p))
        return {
            "user_message": assistant.message_view(user_msg),
            "assistant_message": assistant.message_view(bot),
        }

    payload = {"thread_id": thread_id, **body.model_dump(mode="json")}
    return idempotent_post(db, p, "assistant.messages", idempotency_key, payload, make)


@router.post("/assistant/messages/{message_id}/apply")
def apply_message(message_id: str, p: PM, db: DB, body: ApplyIn | None = None) -> dict[str, Any]:
    """Apply all (default) or the selected actions. Already applied indices are skipped."""
    assert p.org is not None
    msg = db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.id == message_id, AssistantMessage.org_id == p.org_id)
        .with_for_update()
    ).scalar_one_or_none()
    if msg is None:
        raise NotFound("message not found")
    results = assistant.apply(db, p.org, msg, body.actions if body else None, _uid(p))
    return {"results": results, "message": assistant.message_view(msg)}

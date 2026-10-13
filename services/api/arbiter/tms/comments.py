"""Comments and client queries per segment.

kind "comment": internal to the vendor side (PM, API). kind "query": a question to the
client. Client users see only queries and answer them by replying in the thread; a new
query emits the webhook event job.query.opened. A thread is resolved on its root.
Mentions are user ids, e-mails or names given explicitly plus every "@word" in the body.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.errors import Forbidden, Invalid, NotFound
from arbiter.models import Job, SegmentComment, new_id, utcnow

KINDS = ("comment", "query")
_MENTION = re.compile(r"(?<![\w.])@([\w.+-]+(?:@[\w-]+(?:\.[\w-]+)+)?)")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def mentions_of(body: str, explicit: list[str] | None) -> list[str]:
    found = [m.group(1).rstrip(".") for m in _MENTION.finditer(body)]
    out: list[str] = []
    for m in [*(explicit or []), *found]:
        m = m.strip()
        if m and m not in out:
            out.append(m[:120])
    return out[:20]


def view(c: SegmentComment) -> dict[str, Any]:
    return {
        "id": c.id,
        "job_id": c.job_id,
        "segment_id": c.segment_id,
        "thread_id": c.thread_id,
        "parent_id": None if c.thread_id == c.id else c.thread_id,
        "kind": c.kind,
        "author_id": c.author_id,
        "author_role": c.author_role,
        "body": c.body,
        "mentions": list(c.mentions or []),
        "resolved": c.resolved,
        "resolved_by": c.resolved_by,
        "resolved_at": _iso(c.resolved_at),
        "created_at": _iso(c.created_at),
    }


def create(
    session: Session,
    job: Job,
    *,
    role: str,
    actor: str,
    body: str,
    kind: str,
    segment_id: str | None,
    parent_id: str | None,
    mentions: list[str] | None,
) -> SegmentComment:
    from arbiter import webhooks

    body = body.strip()
    if not body:
        raise Invalid("the comment is empty")
    root: SegmentComment | None = None
    if parent_id:
        root = session.get(SegmentComment, parent_id)
        if root is None or root.job_id != job.id:
            raise NotFound("comment not found")
        if root.thread_id != root.id:
            root = session.get(SegmentComment, root.thread_id)
            assert root is not None
        if role == "client" and root.kind != "query":
            raise NotFound("comment not found")
        kind, segment_id = root.kind, root.segment_id
    else:
        if kind not in KINDS:
            raise Invalid("kind must be comment or query")
        if role == "client":
            raise Forbidden("clients answer queries; they cannot open threads")
    cid = new_id("cmt")
    c = SegmentComment(
        id=cid,
        org_id=job.org_id,
        job_id=job.id,
        segment_id=segment_id,
        thread_id=root.id if root else cid,
        kind=kind,
        author_id=actor,
        author_role=role,
        body=body[:10_000],
        mentions=mentions_of(body, mentions),
        resolved=False,
    )
    session.add(c)
    if root is not None and root.resolved and role == "client":
        # The client wrote again on a resolved query: it needs the vendor's attention again.
        root.resolved, root.resolved_by, root.resolved_at = False, None, None
    session.flush()
    if root is None and kind == "query":
        webhooks.emit(
            session,
            job.org_id,
            "job.query.opened",
            {"job_id": job.id, "segment_id": segment_id, "comment_id": c.id, "body": c.body[:500]},
        )
    return c


def listing(
    session: Session,
    job: Job,
    *,
    role: str,
    segment_id: str | None = None,
    kind: str | None = None,
    resolved: bool | None = None,
) -> list[SegmentComment]:
    q = select(SegmentComment).where(SegmentComment.job_id == job.id)
    if role == "client":
        q = q.where(SegmentComment.kind == "query")
    elif kind:
        q = q.where(SegmentComment.kind == kind)
    if segment_id:
        q = q.where(SegmentComment.segment_id == segment_id)
    rows = list(session.execute(q.order_by(SegmentComment.created_at, SegmentComment.id)).scalars())
    if resolved is not None:
        roots = {c.id: c.resolved for c in rows if c.thread_id == c.id}
        rows = [c for c in rows if roots.get(c.thread_id, False) == resolved]
    return rows


def resolve(session: Session, c: SegmentComment, *, resolved: bool, role: str, actor: str) -> SegmentComment:
    if c.thread_id != c.id:
        root = session.get(SegmentComment, c.thread_id)
        assert root is not None
        c = root
    if role == "client" and c.kind != "query":
        raise NotFound("comment not found")
    c.resolved = resolved
    c.resolved_by = actor if resolved else None
    c.resolved_at = utcnow() if resolved else None
    session.flush()
    return c


def open_queries(session: Session, org_id: str, limit: int, offset: int) -> list[SegmentComment]:
    """Unresolved query threads of the org (the client portal's inbox), newest first."""
    q = (
        select(SegmentComment)
        .where(
            SegmentComment.org_id == org_id,
            SegmentComment.kind == "query",
            SegmentComment.thread_id == SegmentComment.id,
            SegmentComment.resolved.is_(False),
        )
        .order_by(SegmentComment.created_at.desc(), SegmentComment.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.execute(q).scalars())

"""Transactional email.

Every email is queued: `queue_email()` writes an email_messages row and an `email.send`
work item in the caller's transaction, and the worker sends it in its own transaction.
So a failing mail server never rolls back the change that caused the email (a delivered
job stays delivered), and a rolled-back change never sends an email.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.models import (
    AccountToken,
    EmailMessage,
    FileAsset,
    Job,
    Organization,
    Payout,
    Project,
    ReviewerProfile,
    User,
    utcnow,
)
from arbiter.notify.mailer import OutgoingEmail, get_mailer
from arbiter.notify.templates import REASON_TEXT, TEMPLATES, render
from arbiter.pipeline.queue import enqueue

log = logging.getLogger("arbiter.notify")

__all__ = [
    "consume_token",
    "deliver",
    "issue_token",
    "job_event",
    "mark_failed",
    "payout_sent",
    "queue_email",
    "request_password_reset",
    "reviewer_welcome",
    "send_invite",
]


def queue_email(
    session: Session,
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    org_id: str | None = None,
    user_id: str | None = None,
    idempotency_key: str | None = None,
) -> EmailMessage:
    """Queue one email (same transaction as the caller). The same idempotency key queues once."""
    if template not in TEMPLATES:
        raise KeyError(f"unknown email template {template!r}")
    if idempotency_key:
        existing = session.execute(
            select(EmailMessage).where(EmailMessage.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    settings = get_settings()
    subject = render(template, context, web_base_url=settings.web_base_url).subject
    msg = EmailMessage(
        org_id=org_id,
        user_id=user_id,
        to_address=to,
        template=template,
        subject=subject[:300],
        context={k: v for k, v in context.items()},
        status="queued",
        idempotency_key=idempotency_key,
    )
    session.add(msg)
    session.flush()
    enqueue(session, "email.send", {"message_id": msg.id}, idempotency_key=f"eml:{msg.id}")
    return msg


def deliver(session: Session, message_id: str) -> None:
    """Worker step for `email.send`. Raises on failure so the queue retries with backoff."""
    msg = session.get(EmailMessage, message_id)
    if msg is None or msg.status in ("sent", "logged"):
        return
    settings = get_settings()
    rendered = render(msg.template, dict(msg.context or {}), web_base_url=settings.web_base_url)
    mailer = get_mailer(settings)
    provider_id = mailer.send(
        OutgoingEmail(to=msg.to_address, subject=rendered.subject, text=rendered.text, html=rendered.html)
    )
    msg.attempts += 1
    msg.backend = mailer.name
    msg.provider_id = provider_id[:200]
    msg.sent_at = utcnow()
    msg.last_error = None
    if mailer.name == "log":
        msg.status = "logged"
        msg.body_text = rendered.text  # dev/test only: lets tests and e2e follow links
    else:
        msg.status = "sent"
        msg.context = {}  # single-use links do not stay in the database


def mark_failed(session: Session, message_id: str, error: str) -> None:
    """Called by the worker when the `email.send` item is dead (attempts exhausted)."""
    msg = session.get(EmailMessage, message_id)
    if msg is None or msg.status in ("sent", "logged"):
        return
    msg.status = "failed"
    msg.last_error = error[:500]
    msg.context = {}


# --------------------------------------------------------------------------- account tokens


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(session: Session, user: User, purpose: str, ttl: timedelta) -> str:
    """New single-use token; every older unused token of the same purpose stops working."""
    now = utcnow()
    session.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    session.add(AccountToken(user_id=user.id, purpose=purpose, token_hash=_hash(token), expires_at=now + ttl))
    session.flush()
    return token


def consume_token(session: Session, token: str, purposes: tuple[str, ...]) -> User | None:
    """The user of a valid token (marked used), or None when unknown, used or expired."""
    if not token or len(token) > 200:
        return None
    row = session.execute(
        select(AccountToken).where(AccountToken.token_hash == _hash(token)).with_for_update()
    ).scalar_one_or_none()
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now or row.purpose not in purposes:
        return None
    row.used_at = now
    return session.get(User, row.user_id)


def recent_tokens(session: Session, user: User, purpose: str, within: timedelta) -> int:
    since = utcnow() - within
    rows = session.execute(
        select(AccountToken.id).where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.created_at >= since,
        )
    ).all()
    return len(rows)


RESET_LIMIT_PER_HOUR = 5


def request_password_reset(session: Session, email: str) -> bool:
    """Queue a reset email when the account exists. Returns whether one was queued.

    The HTTP endpoint answers the same either way, so it never reveals which addresses exist.
    """
    user = session.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if user is None or not user.is_active:
        return False
    if recent_tokens(session, user, "reset", timedelta(hours=1)) >= RESET_LIMIT_PER_HOUR:
        log.info("password reset rate limit hit for user %s", user.id)
        return False
    settings = get_settings()
    minutes = settings.password_reset_ttl_minutes
    token = issue_token(session, user, "reset", timedelta(minutes=minutes))
    link = f"{settings.web_base_url.rstrip('/')}/reset-password?token={token}"
    queue_email(
        session,
        to=user.email,
        template="password_reset",
        context={"name": user.name or user.email, "link": link, "minutes": minutes},
        org_id=user.org_id,
        user_id=user.id,
    )
    return True


def send_invite(session: Session, user: User, inviter: str, org_name: str) -> EmailMessage:
    """Invitation with a set-password link (the reset page accepts invite tokens too)."""
    settings = get_settings()
    hours = settings.invite_ttl_hours
    token = issue_token(session, user, "invite", timedelta(hours=hours))
    link = f"{settings.web_base_url.rstrip('/')}/reset-password?token={token}&invite=1"
    return queue_email(
        session,
        to=user.email,
        template="user_invite",
        context={
            "name": user.name or user.email,
            "inviter": inviter,
            "org_name": org_name,
            "link": link,
            "hours": hours,
        },
        org_id=user.org_id,
        user_id=user.id,
    )


# --------------------------------------------------------------------------- domain events


def _job_recipients(session: Session, job: Job, project: Project | None) -> list[User]:
    """The project creator when active; otherwise every active PM of the organization."""
    if project is not None and project.created_by:
        creator = session.get(User, project.created_by)
        if creator is not None and creator.is_active and creator.org_id == job.org_id:
            return [creator]
    return list(
        session.execute(
            select(User)
            .where(User.org_id == job.org_id, User.role == "pm", User.is_active.is_(True))
            .order_by(User.created_at)
        ).scalars()
    )


def job_event(session: Session, job: Job, event: str, reason: str | None = None) -> int:
    """Email for job.delivered / job.needs_attention, queued next to the webhook emit.

    Never raises: an email problem must not fail the pipeline step that triggered it.
    """
    if event not in ("job.delivered", "job.needs_attention"):
        return 0
    try:
        with session.begin_nested():
            project = session.get(Project, job.project_id)
            fa = session.get(FileAsset, job.file_id) if job.file_id else None
            template = "job_delivered" if event == "job.delivered" else "job_needs_attention"
            n = 0
            for user in _job_recipients(session, job, project):
                ctx: dict[str, Any] = {
                    "name": user.name or user.email,
                    "filename": fa.filename if fa else job.id,
                    "target_lang": job.target_lang,
                    "project_name": project.name if project else job.project_id,
                    "job_id": job.id,
                }
                if template == "job_needs_attention":
                    ctx["reason_text"] = REASON_TEXT.get(reason or "", "A step of this job needs a decision.")
                key = f"{event}:{job.id}:{reason or ''}:{user.id}"
                queue_email(
                    session,
                    to=user.email,
                    template=template,
                    context=ctx,
                    org_id=job.org_id,
                    user_id=user.id,
                    idempotency_key=key[:160],
                )
                n += 1
            return n
    except Exception:  # noqa: BLE001  (logged and swallowed on purpose, see docstring)
        log.exception("could not queue %s email for job %s", event, job.id)
        return 0


def reviewer_welcome(session: Session, user: User) -> None:
    queue_email(
        session,
        to=user.email,
        template="reviewer_welcome",
        context={"name": user.name or user.email},
        user_id=user.id,
        idempotency_key=f"reviewer_welcome:{user.id}",
    )


def payout_sent(session: Session, payout: Payout) -> None:
    """Reviewer email when a payout leaves; never raises (the payout is already sent)."""
    try:
        with session.begin_nested():
            profile = session.get(ReviewerProfile, payout.reviewer_id)
            user = session.get(User, profile.user_id) if profile else None
            if user is None or not user.is_active:
                return
            queue_email(
                session,
                to=user.email,
                template="payout_sent",
                context={
                    "name": user.name or user.email,
                    "amount": str(payout.amount),
                    "currency": payout.currency,
                    "method": payout.method or (profile.payout_method if profile else "") or "transfer",
                    "reference": payout.provider_ref or payout.id,
                },
                user_id=user.id,
                idempotency_key=f"payout_sent:{payout.id}",
            )
    except Exception:  # noqa: BLE001
        log.exception("could not queue payout email for %s", payout.id)


def org_name(session: Session, org_id: str | None) -> str:
    org = session.get(Organization, org_id) if org_id else None
    return org.name if org else ""

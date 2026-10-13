"""Email: templates, queue + worker delivery, SMTP transport, password reset, pipeline hooks."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from api_helpers import client, register
from sqlalchemy import select
from test_api_cust_helpers import drain, order

from arbiter import notify
from arbiter.config import Settings
from arbiter.models import AccountToken, EmailMessage, Payout, ReviewerProfile, User, WorkItem, utcnow
from arbiter.notify import mailer as mailer_mod
from arbiter.notify.templates import TEMPLATES, render, template_fields


def _emails(db, template: str | None = None) -> list[EmailMessage]:
    db.expire_all()
    q = select(EmailMessage).order_by(EmailMessage.created_at)
    if template:
        q = q.where(EmailMessage.template == template)
    return list(db.execute(q).scalars())


SAMPLE = {
    "name": "Ana <b>",
    "inviter": "Pat",
    "org_name": "Acme",
    "link": "https://app.example.com/reset-password?token=abc",
    "hours": 72,
    "minutes": 60,
    "filename": "notes.md",
    "target_lang": "sr",
    "project_name": "Launch",
    "job_id": "job_1",
    "reason_text": "Some segments are waiting for a human reviewer.",
    "amount": "12.40",
    "currency": "EUR",
    "method": "bank",
    "reference": "ref-1",
    "subject": "Job offer",
    "body": "Review of 120 words, en > sr.",
}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_renders_text_and_html_from_one_source(name):
    tpl = TEMPLATES[name]
    assert template_fields(name) <= set(tpl.required) | set(tpl.optional), "every placeholder must be declared"
    out = render(name, SAMPLE, web_base_url="https://app.example.com/")
    assert out.subject and "\n" not in out.subject
    assert "Ana <b>" in out.text and "Ana &lt;b&gt;" in out.html and "<b>" not in out.html.split("<body")[1]
    if tpl.action_label:
        assert tpl.action_label in out.text and tpl.action_label in out.html
    for body in (out.subject, out.text, out.html):
        assert "—" not in body  # no em dashes in copy
    with pytest.raises(ValueError):
        render(name, {}, web_base_url="https://x")


def test_queue_then_worker_delivers_with_log_backend(db):
    msg = notify.queue_email(db, to="a@example.com", template="reviewer_welcome", context={"name": "Ana"})
    again = notify.queue_email(
        db, to="a@example.com", template="reviewer_welcome", context={"name": "Ana"}, idempotency_key="k1"
    )
    same = notify.queue_email(
        db, to="a@example.com", template="reviewer_welcome", context={"name": "Ana"}, idempotency_key="k1"
    )
    assert again.id == same.id
    db.commit()
    assert db.execute(select(WorkItem).where(WorkItem.kind == "email.send")).scalars().all()
    drain()
    db.expire_all()
    m = db.get(EmailMessage, msg.id)
    assert m.status == "logged" and m.backend == "log" and m.sent_at is not None
    assert "qualification test" in m.body_text and "/reviewer" in m.body_text


class _Boom:
    name = "smtp"

    def send(self, email):
        raise ConnectionError("smtp down")


def test_failing_mailer_retries_then_marks_failed_without_touching_cause(db):
    msg = notify.queue_email(db, to="a@example.com", template="reviewer_welcome", context={"name": "Ana"})
    db.commit()
    mailer_mod.use(_Boom())
    try:
        item = db.execute(select(WorkItem).where(WorkItem.kind == "email.send")).scalar_one()
        item.max_attempts = 1
        db.commit()
        drain()
    finally:
        mailer_mod.use(None)
    db.expire_all()
    m = db.get(EmailMessage, msg.id)
    assert m.status == "failed" and "smtp down" in (m.last_error or "") and m.context == {}


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.sent.append(msg)
        return {}

    def quit(self):
        self.calls.append("quit")


def test_smtp_mailer_starttls_login_multipart(monkeypatch):
    monkeypatch.setattr(mailer_mod.smtplib, "SMTP", _FakeSMTP)
    s = Settings(
        env="test",
        mail_backend="smtp",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="u",
        smtp_password="p",
        mail_from="Arbiter <no-reply@example.com>",
        mail_reply_to="support@example.com",
    )
    out = render("password_reset", SAMPLE, web_base_url="https://app.example.com")
    mid = mailer_mod.SmtpMailer(s).send(
        mailer_mod.OutgoingEmail(to="ana@example.com", subject=out.subject, text=out.text, html=out.html)
    )
    conn = _FakeSMTP.instances[-1]
    assert conn.host == "smtp.example.com" and conn.calls[:3] == ["ehlo", "starttls", "ehlo"]
    assert ("login", "u") in conn.calls and conn.calls[-1] == "quit"
    msg = conn.sent[0]
    assert msg["To"] == "ana@example.com" and msg["Reply-To"] == "support@example.com"
    assert msg["Message-ID"] == mid and mid.endswith("@example.com>")
    assert msg.is_multipart() and {p.get_content_type() for p in msg.iter_parts()} == {
        "text/plain",
        "text/html",
    }
    # tests never get a real SMTP mailer from the factory
    assert mailer_mod.get_mailer(s).name == "log"
    with pytest.raises(RuntimeError):
        mailer_mod.SmtpMailer(Settings(env="test", smtp_host=""))


def _link_token(body: str) -> str:
    m = re.search(r"reset-password\?token=([A-Za-z0-9_\-]+)", body)
    assert m, body
    return m.group(1)


def test_password_reset_flow(db):
    c = client()
    register(c, email="pm@example.com")
    assert c.post("/v1/auth/password/forgot", json={"email": "nobody@example.com"}).status_code == 202
    r = c.post("/v1/auth/password/forgot", json={"email": "PM@example.com"})
    assert r.status_code == 202 and r.json() == {"ok": True}
    drain()
    mails = _emails(db, "password_reset")
    assert len(mails) == 1 and mails[0].to_address == "pm@example.com"
    token = _link_token(mails[0].body_text)
    stored = db.execute(select(AccountToken)).scalar_one()
    assert token not in stored.token_hash and len(stored.token_hash) == 64

    short = c.post("/v1/auth/password/reset", json={"token": token, "password": "short"})
    assert short.status_code == 422
    ok = c.post("/v1/auth/password/reset", json={"token": token, "password": "new-secret-99"})
    assert ok.status_code == 200 and ok.json()["token"] and ok.json()["user"]["email"] == "pm@example.com"
    reused = c.post("/v1/auth/password/reset", json={"token": token, "password": "other-secret-99"})
    assert reused.status_code == 422 and reused.json()["error"]["code"] == "invalid_token"
    assert (
        c.post("/v1/auth/login", json={"email": "pm@example.com", "password": "secret-123"}).status_code
        == 401
    )
    assert (
        c.post("/v1/auth/login", json={"email": "pm@example.com", "password": "new-secret-99"}).status_code
        == 200
    )


def test_reset_token_expiry_supersede_and_rate_limit(db):
    c = client()
    register(c, email="pm@example.com")
    user = db.execute(select(User).where(User.email == "pm@example.com")).scalar_one()
    first = notify.issue_token(db, user, "reset", timedelta(minutes=60))
    second = notify.issue_token(db, user, "reset", timedelta(minutes=60))
    expired = notify.issue_token(db, user, "invite", timedelta(minutes=60))
    db.execute(
        AccountToken.__table__.update()
        .where(AccountToken.purpose == "invite")
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    assert notify.consume_token(db, first, ("reset",)) is None  # superseded by the newer link
    assert notify.consume_token(db, expired, ("invite",)) is None
    assert notify.consume_token(db, second, ("invite",)) is None  # wrong purpose
    assert notify.consume_token(db, second, ("reset",)).id == user.id
    db.commit()
    for _ in range(10):
        c.post("/v1/auth/password/forgot", json={"email": "pm@example.com"})
    assert len(_emails(db, "password_reset")) == notify.RESET_LIMIT_PER_HOUR - 2  # 2 issued above


def test_invite_email_is_sent_and_link_sets_password(db):
    """Team invites (platform) are delivered through notify: one queued email with the accept link."""
    c = client()
    h = register(c, email="pm@example.com")
    r = c.post(
        "/v1/users/invite", headers=h, json={"email": "new@example.com", "name": "New", "role": "client"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["email_sent"] is True
    db.commit()
    drain()
    mail = _emails(db, "user_invite")[0]
    assert mail.to_address == "new@example.com" and mail.status == "logged"
    assert "invited you to join Acme GmbH" in mail.body_text and "168 hours" in mail.body_text
    m = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", mail.body_text)
    assert m, mail.body_text
    r = c.post("/v1/auth/invite/accept", json={"token": m.group(1), "password": "welcome-123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "client"
    # invite tokens are not password-reset tokens
    assert (
        c.post("/v1/auth/password/reset", json={"token": m.group(1), "password": "x" * 12}).status_code == 422
    )


def test_job_delivered_email_goes_to_project_creator(db):
    c = client()
    h = register(c, email="pm@example.com")
    prj = order(c, h, "auto")
    drain()
    mails = _emails(db, "job_delivered")
    assert len(mails) == 1 and mails[0].to_address == "pm@example.com"
    assert mails[0].status == "logged" and f"/app/jobs/{prj['jobs'][0]['id']}" in mails[0].body_text
    assert mails[0].subject == "Delivered: notes.md (sr)"


def test_job_needs_attention_email_on_human_review(db):
    c = client()
    h = register(c, email="pm@example.com")
    order(c, h, "full")
    drain()
    mails = _emails(db, "job_needs_attention")
    assert mails and "waiting for a human reviewer" in mails[0].body_text


def test_email_failure_never_fails_the_job(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("template store down")

    monkeypatch.setattr(notify, "queue_email", boom)
    c = client()
    h = register(c)
    prj = order(c, h, "auto")
    drain()
    assert c.get(f"/v1/jobs/{prj['jobs'][0]['id']}", headers=h).json()["state"] == "delivered"


def test_reviewer_welcome_and_payout_sent(db):
    c = client()
    r = c.post(
        "/v1/reviewers/apply",
        json={
            "name": "Rev",
            "email": "rev@example.com",
            "password": "secret-123",
            "country": "RS",
            "pairs": [{"source_lang": "en", "target_lang": "sr"}],
        },
    )
    assert r.status_code == 201, r.text
    assert [m.to_address for m in _emails(db, "reviewer_welcome")] == ["rev@example.com"]
    prof = db.execute(select(ReviewerProfile)).scalar_one()
    p = Payout(
        reviewer_id=prof.id,
        amount=Decimal("12.40"),
        currency="EUR",
        method="bank",
        idempotency_key="pay-1",
        state="sent",
        provider_ref="mock-ref",
    )
    db.add(p)
    db.flush()
    notify.payout_sent(db, p)
    notify.payout_sent(db, p)  # retried run: still one email
    db.commit()
    drain()
    mails = _emails(db, "payout_sent")
    assert len(mails) == 1 and "12.40 EUR" in mails[0].body_text and "mock-ref" in mails[0].body_text

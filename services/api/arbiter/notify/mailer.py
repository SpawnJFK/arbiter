"""Mail transports behind one protocol, picked by ARBITER_MAIL_BACKEND.

* LogMailer (dev, test): writes a line to the log; the caller keeps the body in
  email_messages so tests and the e2e run can read links back.
* SmtpMailer: plain SMTP with STARTTLS or implicit TLS. Works with any transactional
  provider that offers SMTP, so switching provider is a settings change.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Protocol

from arbiter.config import Settings, get_settings

log = logging.getLogger("arbiter.mail")


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    headers: dict[str, str] = field(default_factory=dict)


class Mailer(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> str:
        """Send one message; returns the provider/message id. Raises on failure."""
        ...


class LogMailer:
    name = "log"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.sent: list[OutgoingEmail] = []

    def send(self, email: OutgoingEmail) -> str:
        self.sent.append(email)
        msg_id = make_msgid(domain="arbiter.local")
        log.info("email (log backend) to=%s subject=%r id=%s", email.to, email.subject, msg_id)
        return msg_id


def build_message(settings: Settings, email: OutgoingEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = email.to
    msg["Subject"] = email.subject
    msg["Date"] = formatdate(localtime=False)
    domain = parseaddr(settings.mail_from)[1].rpartition("@")[2] or "localhost"
    msg["Message-ID"] = make_msgid(domain=domain)
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to
    for k, v in email.headers.items():
        msg[k] = v
    msg.set_content(email.text)
    msg.add_alternative(email.html, subtype="html")
    return msg


class SmtpMailer:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host:
            raise RuntimeError("ARBITER_SMTP_HOST must be set when ARBITER_MAIL_BACKEND=smtp")
        self._settings = settings

    def _connect(self) -> smtplib.SMTP:
        s = self._settings
        ctx = ssl.create_default_context()
        if s.smtp_security == "ssl":
            return smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=ctx)
        conn = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
        if s.smtp_security == "starttls":
            conn.ehlo()
            conn.starttls(context=ctx)
            conn.ehlo()
        return conn

    def send(self, email: OutgoingEmail) -> str:
        s = self._settings
        msg = build_message(s, email)
        conn = self._connect()
        try:
            if s.smtp_username:
                conn.login(s.smtp_username, s.smtp_password)
            refused = conn.send_message(msg)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
        finally:
            try:
                conn.quit()
            except smtplib.SMTPException:
                conn.close()
        return str(msg["Message-ID"])


_override: Mailer | None = None


def get_mailer(settings: Settings | None = None) -> Mailer:
    if _override is not None:
        return _override
    s = settings or get_settings()
    if s.mail_backend == "smtp" and not s.is_test:  # tests never reach a real server
        return SmtpMailer(s)
    return LogMailer(s)


def use(mailer: Mailer | None) -> None:
    """Replace the mailer (tests). `use(None)` restores the configured one."""
    global _override
    _override = mailer

"""Email templates. One source per email; the plain-text and HTML bodies are rendered from it.

All copy is English (D-045). Values are inserted with str.format and HTML-escaped for the
HTML body. Templates never carry segment text or file content, only names and links.
"""

from __future__ import annotations

import html
import string
from dataclasses import dataclass, field
from typing import Any

PRODUCT = "Arbiter"  # working name; one place to change it


@dataclass(frozen=True)
class Template:
    subject: str
    paragraphs: tuple[str, ...]
    action_label: str = ""
    action_url: str = ""  # a context key holding the URL, e.g. "{link}"
    footer: str = ""
    required: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


TEMPLATES: dict[str, Template] = {
    "reviewer_welcome": Template(
        subject=f"Welcome to {PRODUCT}, {{name}}",
        paragraphs=(
            "Hi {name},",
            f"Thanks for applying to review translations on {PRODUCT}.",
            "Your next step is the qualification test for your language pairs. "
            "Once you pass it, review tasks appear in your queue and you are paid per task.",
        ),
        action_label="Open your reviewer workspace",
        action_url="{web}/reviewer",
        required=("name",),
    ),
    "user_invite": Template(
        subject=f"You are invited to {{org_name}} on {PRODUCT}",
        paragraphs=(
            "Hi {name},",
            f"{{inviter}} invited you to join {{org_name}} on {PRODUCT}.",
            "Set your password to activate your account. The link works once and expires in {hours} hours.",
        ),
        action_label="Set your password",
        action_url="{link}",
        footer="If you did not expect this invitation, you can ignore this email.",
        required=("name", "inviter", "org_name", "link", "hours"),
    ),
    "job_delivered": Template(
        subject="Delivered: {filename} ({target_lang})",
        paragraphs=(
            "Hi {name},",
            "The translation of {filename} into {target_lang} in project {project_name} is delivered.",
            "The translated file and its evidence pack are ready to download.",
        ),
        action_label="Open the job",
        action_url="{web}/app/jobs/{job_id}",
        required=("name", "filename", "target_lang", "project_name", "job_id"),
    ),
    "job_needs_attention": Template(
        subject="Needs attention: {filename} ({target_lang})",
        paragraphs=(
            "Hi {name},",
            "The job {filename} into {target_lang} in project {project_name} needs attention.",
            "{reason_text}",
        ),
        action_label="Open the job",
        action_url="{web}/app/jobs/{job_id}",
        required=("name", "filename", "target_lang", "project_name", "job_id", "reason_text"),
    ),
    "payout_sent": Template(
        subject="Payout sent: {amount} {currency}",
        paragraphs=(
            "Hi {name},",
            "We sent your payout of {amount} {currency} by {method}.",
            "Reference: {reference}. Depending on the method it can take a few working days to arrive.",
        ),
        action_label="See your earnings",
        action_url="{web}/reviewer/earnings",
        required=("name", "amount", "currency", "method", "reference"),
    ),
    "password_reset": Template(
        subject=f"Reset your {PRODUCT} password",
        paragraphs=(
            "Hi {name},",
            "Someone asked to reset the password of this account. "
            "If it was you, choose a new password with the link below. "
            "It works once and expires in {minutes} minutes.",
        ),
        action_label="Choose a new password",
        action_url="{link}",
        footer="If you did not ask for this, ignore this email. Your password stays the same.",
        required=("name", "link", "minutes"),
    ),
}

REASON_TEXT: dict[str, str] = {
    "human_review": "Some segments are waiting for a human reviewer.",
    "client_review": "Every segment is done and the job is waiting for your approval.",
    "deadline": "The deadline passed with segments still open. Your organization's policy is to wait "
    "for a reviewer, so nothing ships until a human finishes them.",
}


class _Values(dict):
    """format_map helper: a missing key renders as an empty string instead of raising."""

    def __missing__(self, key: str) -> str:
        return ""


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def render(name: str, context: dict[str, Any], *, web_base_url: str) -> Rendered:
    tpl = TEMPLATES.get(name)
    if tpl is None:
        raise KeyError(f"unknown email template {name!r}")
    missing = [k for k in tpl.required if context.get(k) in (None, "")]
    if missing:
        raise ValueError(f"template {name!r} needs {', '.join(missing)}")
    plain = _Values({k: str(v) for k, v in context.items()})
    plain["web"] = web_base_url.rstrip("/")
    escaped = _Values({k: html.escape(v, quote=True) for k, v in plain.items()})

    subject = tpl.subject.format_map(plain).replace("\n", " ").strip()
    paragraphs = [p.format_map(plain) for p in tpl.paragraphs]
    url = tpl.action_url.format_map(plain) if tpl.action_url else ""
    footer = tpl.footer.format_map(plain) if tpl.footer else ""

    text_parts = [*paragraphs]
    if url:
        text_parts.append(f"{tpl.action_label}: {url}")
    if footer:
        text_parts.append(footer)
    text_parts.append(f"{PRODUCT}")
    text = "\n\n".join(text_parts) + "\n"

    p_style = (
        "margin:0 0 16px;font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d1f24"
    )
    body = [f'<p style="{p_style}">{p.format_map(escaped)}</p>' for p in tpl.paragraphs]
    if url:
        safe_url = html.escape(url, quote=True)
        body.append(
            f'<p style="margin:24px 0"><a href="{safe_url}" style="display:inline-block;padding:10px 18px;'
            "border-radius:6px;background:#1d1f24;color:#ffffff;text-decoration:none;"
            f'font:600 14px -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
            f"{html.escape(tpl.action_label)}</a></p>"
            f'<p style="{p_style};font-size:13px;color:#5b5f69">Or paste this link into your browser: '
            f"{safe_url}</p>"
        )
    if footer:
        body.append(f'<p style="{p_style};font-size:13px;color:#5b5f69">{tpl.footer.format_map(escaped)}</p>')
    html_doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(subject)}</title></head>"
        '<body style="margin:0;padding:24px;background:#f6f6f7">'
        '<div style="max-width:560px;margin:0 auto;padding:32px;background:#ffffff;border-radius:8px">'
        + "".join(body)
        + f'<p style="{p_style};font-size:12px;color:#8a8e97;margin-top:32px">{PRODUCT}</p>'
        "</div></body></html>"
    )
    return Rendered(subject=subject, text=text, html=html_doc)


def template_fields(name: str) -> set[str]:
    """Every placeholder a template uses (tests check required keys cover them)."""
    tpl = TEMPLATES[name]
    out: set[str] = set()
    for piece in (tpl.subject, tpl.action_url, tpl.footer, *tpl.paragraphs):
        out |= _fields(piece)
    return out - {"web"}

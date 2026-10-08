"""UI string localization store: locales and translated messages (platform admin).

English is the source catalog and lives in the web repo; "en" is implicit (never stored).
Translations are imported/edited here, so a new language or a fixed string needs no redeploy.

Placeholder safety (ICU-lite): a translation must use the same top-level arguments as its
English source: `{name}` and the argument of `{count, plural, ...}` / `{x, select, ...}`.
Text inside plural/select branches (depth > 1) is not an argument. Apostrophe quoting
('{literal}') follows ICU: a quote starts quoting only before a brace; '' is a literal quote.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from arbiter.errors import Invalid, NotFound
from arbiter.models import UiLocale, UiMessage, utcnow

SOURCE_LOCALE = "en"
MAX_KEYS = 20_000
MAX_KEY_LEN = 200
MAX_VALUE_LEN = 5000
_ARG = re.compile(r"\s*([^\s,{}]+)")


def placeholders(message: str) -> set[str]:
    """Top-level ICU argument names of a message."""
    out: set[str] = set()
    depth, i, n = 0, 0, len(message)
    while i < n:
        ch = message[i]
        if ch == "'":
            if i + 1 < n and message[i + 1] == "'":
                i += 2
                continue
            if i + 1 < n and message[i + 1] in "{}":
                end = message.find("'", i + 1)
                i = n if end < 0 else end + 1
                continue
        elif ch == "{":
            if depth == 0:
                m = _ARG.match(message, i + 1)
                if m:
                    out.add(m.group(1))
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    return out


def placeholder_errors(messages: dict[str, str], source: dict[str, str]) -> dict[str, Any]:
    """Per key: expected vs got argument names, for keys present in `source` with a value."""
    bad: dict[str, Any] = {}
    for key, value in messages.items():
        if not value or key not in source:
            continue
        want, got = placeholders(source[key]), placeholders(value)
        if want != got:
            bad[key] = {"expected": sorted(want), "got": sorted(got)}
    return bad


def locale_view(session: Session, loc: UiLocale) -> dict[str, Any]:
    count, last = session.execute(
        select(func.count(UiMessage.id), func.max(UiMessage.updated_at)).where(UiMessage.locale == loc.locale)
    ).one()
    updated = last or loc.created_at
    return {
        "locale": loc.locale,
        "name": loc.name,
        "enabled": loc.enabled,
        "message_count": int(count),
        "updated_at": updated.isoformat() if updated else None,
    }


SOURCE_VIEW = {
    "locale": SOURCE_LOCALE,
    "name": "English",
    "enabled": True,
    "message_count": None,
    "updated_at": None,
}


def list_locales(session: Session, *, include_disabled: bool) -> list[dict[str, Any]]:
    q = select(UiLocale).order_by(UiLocale.locale)
    if not include_disabled:
        q = q.where(UiLocale.enabled.is_(True))
    return [dict(SOURCE_VIEW)] + [locale_view(session, loc) for loc in session.execute(q).scalars()]


def not_source(locale: str) -> None:
    if locale == SOURCE_LOCALE:
        raise Invalid("en is the source catalog; it lives in the web repo and is not stored here")


def messages_for(session: Session, locale: str, *, include_disabled: bool) -> dict[str, str]:
    if locale == SOURCE_LOCALE:
        return {}
    loc = session.get(UiLocale, locale)
    if loc is None or (not loc.enabled and not include_disabled):
        raise NotFound(f"locale {locale} is not available")
    rows = session.execute(
        select(UiMessage.key, UiMessage.value).where(UiMessage.locale == locale).order_by(UiMessage.key)
    ).all()
    return dict(rows)


def upsert_locale(session: Session, locale: str, name: str, enabled: bool | None) -> UiLocale:
    not_source(locale)
    loc = session.get(UiLocale, locale)
    if loc is None:
        loc = UiLocale(locale=locale, name=name, enabled=bool(enabled))
        session.add(loc)
    else:
        loc.name = name
        if enabled is not None:
            loc.enabled = enabled
    session.flush()
    return loc


def delete_locale(session: Session, locale: str) -> None:
    loc = session.get(UiLocale, locale)
    if loc is None:
        raise NotFound(f"locale {locale} not found")
    session.execute(delete(UiMessage).where(UiMessage.locale == locale))
    session.delete(loc)
    session.flush()


def import_messages(
    session: Session,
    locale: str,
    messages: dict[str, str],
    mode: str,
    source: dict[str, str] | None = None,
) -> dict[str, Any]:
    """merge: upsert the given keys; replace: the locale ends with exactly the given keys.
    An empty value removes the key. A locale without a row is created disabled."""
    not_source(locale)
    if len(messages) > MAX_KEYS:
        raise Invalid(f"at most {MAX_KEYS} keys per request")
    too_long = [k for k in messages if not k or len(k) > MAX_KEY_LEN]
    if too_long:
        raise Invalid(f"keys must be 1-{MAX_KEY_LEN} characters", {"keys": too_long[:50]})
    big = [k for k, v in messages.items() if len(v) > MAX_VALUE_LEN]
    if big:
        raise Invalid(f"values must be at most {MAX_VALUE_LEN} characters", {"keys": big[:50]})
    if source:
        bad = placeholder_errors(messages, source)
        if bad:
            raise Invalid("placeholders differ from the English source", {"placeholders": bad})
    if session.get(UiLocale, locale) is None:
        session.add(UiLocale(locale=locale, name=locale, enabled=False))
        session.flush()
    existing = {
        m.key: m for m in session.execute(select(UiMessage).where(UiMessage.locale == locale)).scalars()
    }
    upserted = deleted = 0
    now = utcnow()
    for key, value in messages.items():
        row = existing.get(key)
        if value == "":
            if row is not None:
                session.delete(row)
                deleted += 1
            continue
        if row is None:
            session.add(UiMessage(locale=locale, key=key, value=value, updated_at=now))
            upserted += 1
        elif row.value != value:
            row.value, row.updated_at = value, now
            upserted += 1
    if mode == "replace":
        for key, row in existing.items():
            if key not in messages:
                session.delete(row)
                deleted += 1
    session.flush()
    total = session.execute(
        select(func.count()).select_from(UiMessage).where(UiMessage.locale == locale)
    ).scalar_one()
    return {"locale": locale, "upserted": upserted, "deleted": deleted, "total": int(total)}

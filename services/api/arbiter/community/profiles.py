"""Reviewer sign-up, profile view, tax/payout details and admin status changes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.billing import ledger
from arbiter.community.errors import Conflict, Invalid, NotFound
from arbiter.models import ReviewerPair, ReviewerProfile, User

LEVELS = ("candidate", "reviewer", "senior", "domain_expert")
STATUSES = ("applied", "active", "suspended", "banned")
PAYOUT_METHODS = ("wise", "paypal", "sepa")
# Platform-operator reporting (EU DAC7 and equivalents) needs all of these before a payout.
TAX_FIELDS = ("legal_name", "tax_id", "address", "date_of_birth", "country", "payout_method")

_hasher = PasswordHasher()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")


def _norm_lang(value: str) -> str:
    lang = (value or "").strip().replace("_", "-").lower()
    if not _LANG.match(lang):
        raise Invalid(f"invalid language code: {value!r}")
    return lang


def _pair_tuple(p: Any) -> tuple[str, str]:
    if isinstance(p, Mapping):
        return _norm_lang(p["source_lang"]), _norm_lang(p["target_lang"])
    src, tgt = p
    return _norm_lang(src), _norm_lang(tgt)


def apply(
    session: Session,
    *,
    name: str,
    email: str,
    password: str,
    country: str,
    pairs: Iterable[Any],
    domains: Iterable[str] = (),
) -> tuple[User, ReviewerProfile]:
    """Create a reviewer user (role "reviewer", no org) and a candidate profile.

    Each requested pair starts in status "testing": the reviewer must pass the language and
    practical tests for it before any task is offered.
    """
    email_n = (email or "").strip().lower()
    if not _EMAIL.match(email_n):
        raise Invalid("invalid email")
    if len(password or "") < 8:
        raise Invalid("password must be at least 8 characters")
    pair_list = list(dict.fromkeys(_pair_tuple(p) for p in pairs))
    if not pair_list:
        raise Invalid("at least one language pair is required")
    if any(s == t for s, t in pair_list):
        raise Invalid("source and target language must differ")
    if session.execute(select(User.id).where(User.email == email_n)).first() is not None:
        raise Conflict("email already registered")
    user = User(email=email_n, name=name.strip(), password_hash=_hasher.hash(password), role="reviewer")
    session.add(user)
    session.flush()
    profile = ReviewerProfile(
        user_id=user.id,
        level="candidate",
        status="applied",
        country=(country or "").strip().upper()[:2],
        domains=[d.strip().lower() for d in domains if d and d.strip()],
    )
    session.add(profile)
    session.flush()
    for src, tgt in pair_list:
        session.add(ReviewerPair(reviewer_id=profile.id, source_lang=src, target_lang=tgt, status="testing"))
    session.flush()
    return user, profile


def verify_password(user: User, password: str) -> bool:
    try:
        return _hasher.verify(user.password_hash, password)
    except Exception:
        return False


def tax_info_complete(profile: ReviewerProfile) -> bool:
    return all(str(getattr(profile, f) or "").strip() for f in TAX_FIELDS)


def get_profile(session: Session, profile_id: str) -> ReviewerProfile:
    profile = session.get(ReviewerProfile, profile_id)
    if profile is None:
        raise NotFound("reviewer not found")
    return profile


def profile_for_user(session: Session, user_id: str) -> ReviewerProfile:
    profile = session.execute(
        select(ReviewerProfile).where(ReviewerProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        raise NotFound("reviewer profile not found")
    return profile


def profile_view(session: Session, profile: ReviewerProfile) -> dict[str, Any]:
    """ReviewerProfile per docs/api-contract.md (plus name/email and admin counters)."""
    user = session.get(User, profile.user_id)
    pairs = session.execute(
        select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id).order_by(ReviewerPair.created_at)
    ).scalars()
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "name": user.name if user else "",
        "email": user.email if user else "",
        "level": profile.level,
        "status": profile.status,
        "score": round(float(profile.score or 0.0), 2),
        "pairs": [
            {
                "source_lang": p.source_lang,
                "target_lang": p.target_lang,
                "status": p.status,
                "score": round(float(p.score or 0.0), 2),
            }
            for p in pairs
        ],
        "domains": list(profile.domains or []),
        "country": profile.country,
        "balance": ledger.money(ledger.account_balance(session, ledger.reviewer_account(profile.id))),
        "payout_threshold": ledger.money(profile.payout_threshold),
        "payout_method": profile.payout_method,
        "tax_info_complete": tax_info_complete(profile),
        "decisions_total": profile.decisions_total,
        "fraud_flags": profile.fraud_flags,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


def update_tax_info(
    session: Session,
    profile: ReviewerProfile,
    *,
    legal_name: str | None = None,
    tax_id: str | None = None,
    address: str | None = None,
    date_of_birth: str | None = None,
    country: str | None = None,
    payout_method: str | None = None,
    payout_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PATCH /reviewer/me. Only the given fields change."""
    if date_of_birth is not None and date_of_birth and not _DATE.match(date_of_birth):
        raise Invalid("date_of_birth must be YYYY-MM-DD")
    if payout_method is not None and payout_method and payout_method not in PAYOUT_METHODS:
        raise Invalid(f"payout_method must be one of {', '.join(PAYOUT_METHODS)}")
    if payout_details is not None and not isinstance(payout_details, dict):
        raise Invalid("payout_details must be an object")
    for field, value in (
        ("legal_name", legal_name),
        ("tax_id", tax_id),
        ("address", address),
        ("date_of_birth", date_of_birth),
        ("payout_method", payout_method),
    ):
        if value is not None:
            setattr(profile, field, value.strip())
    if country is not None:
        profile.country = country.strip().upper()[:2]
    if payout_details is not None:
        profile.payout_details = dict(payout_details)
    session.flush()
    return profile_view(session, profile)


def set_status(session: Session, profile_id: str, status: str, level: str | None = None) -> dict[str, Any]:
    """Admin: change reviewer status (and optionally level)."""
    if status not in STATUSES:
        raise Invalid(f"status must be one of {', '.join(STATUSES)}")
    if level is not None and level not in LEVELS:
        raise Invalid(f"level must be one of {', '.join(LEVELS)}")
    profile = get_profile(session, profile_id)
    profile.status = status
    if level is not None:
        profile.level = level
    session.flush()
    return profile_view(session, profile)


def list_profiles(session: Session, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(ReviewerProfile).order_by(ReviewerProfile.created_at)
    if status:
        stmt = stmt.where(ReviewerProfile.status == status)
    return [profile_view(session, p) for p in session.execute(stmt).scalars()]

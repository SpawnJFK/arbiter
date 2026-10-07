"""Passwords (argon2), session tokens (JWT HS256) and API keys (prefix + argon2 secret).

API key format: `ak_<prefix>.<secret>`. The prefix is stored in clear for lookup; the secret
only as a hash, so a leaked database does not leak usable keys. Shown once on creation.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from arbiter.config import get_settings
from arbiter.models import utcnow

_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw_hash: str, pw: str) -> bool:
    try:
        return _hasher.verify(pw_hash, pw)
    except (VerificationError, ValueError):
        return False


def issue_token(user_id: str, role: str, org_id: str | None) -> str:
    s = get_settings()
    now = utcnow()
    payload = {
        "sub": user_id,
        "role": role,
        "org": org_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def new_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, secret_hash)."""
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return f"ak_{prefix}.{secret}", prefix, _hasher.hash(secret)


def split_api_key(key: str) -> tuple[str, str] | None:
    if not key.startswith("ak_") or "." not in key:
        return None
    prefix, secret = key[3:].split(".", 1)
    return prefix, secret

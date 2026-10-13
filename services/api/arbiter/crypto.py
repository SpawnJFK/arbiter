"""Encryption at rest for secrets stored in the database (engine credentials, D-051).

Fernet (AES-128-CBC + HMAC-SHA256, from `cryptography`) with keys from ARBITER_SECRETS_KEY.
The setting is a comma separated list, newest first: the first key encrypts, every key
decrypts (MultiFernet), so a key can be rotated without a data migration. A value that is
not a valid Fernet key is stretched with SHA-256, so an `openssl rand -hex 32` string works.

Production refuses to encrypt or decrypt without the setting. Dev and test use a fixed,
clearly named dev-only key so local databases keep working.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from arbiter.config import Settings, get_settings

DEV_ONLY_KEY = "dev-only-arbiter-secrets-key-not-for-production"


class SecretsUnavailable(RuntimeError):
    """No usable key (prod without ARBITER_SECRETS_KEY) or a value no key can decrypt."""


def _fernet_for(raw: str) -> Fernet:
    raw = raw.strip()
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def _box(settings: Settings | None = None) -> MultiFernet:
    s = settings or get_settings()
    keys = [k for k in (s.secrets_key or "").split(",") if k.strip()]
    if not keys:
        if s.env == "prod":
            raise SecretsUnavailable("ARBITER_SECRETS_KEY must be set in production")
        keys = [DEV_ONLY_KEY]
    return MultiFernet([_fernet_for(k) for k in keys])


def encrypt(plaintext: str, settings: Settings | None = None) -> str:
    return _box(settings).encrypt(plaintext.encode()).decode()


def decrypt(token: str, settings: Settings | None = None) -> str:
    try:
        return _box(settings).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretsUnavailable("stored secret cannot be decrypted with the configured keys") from e


def hint(secret: str) -> str:
    """What the UI may show after save: the last 4 characters, never more."""
    tail = secret.strip()[-4:]
    return f"...{tail}" if tail else ""

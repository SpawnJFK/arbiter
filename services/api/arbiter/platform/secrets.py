"""Encryption at rest for secrets kept in the database (SSO client secrets, later BYOK keys).

Fernet (AES-128-CBC + HMAC-SHA256, authenticated) from the `cryptography` package, keyed by
ARBITER_SECRETS_KEY. The setting is a comma-separated list for rotation: the first key
encrypts, every key decrypts (MultiFernet), and `rotate()` re-encrypts a token under the
first key. Each entry is either a Fernet key (urlsafe base64 of 32 bytes) or a passphrase,
which is stretched to a key with HKDF-SHA256.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from arbiter.config import get_settings

_HKDF_INFO = b"arbiter-secrets-v1"


class SecretDecryptError(Exception):
    """The ciphertext was not produced by any configured key (or was tampered with)."""


def _key(entry: str) -> bytes:
    entry = entry.strip()
    try:
        raw = base64.urlsafe_b64decode(entry.encode())
        if len(raw) == 32 and len(entry) == 44:
            return entry.encode()
    except (binascii.Error, ValueError):
        pass
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(entry.encode())
    return base64.urlsafe_b64encode(derived)


def _fernet(keys: str | None = None) -> MultiFernet:
    raw = keys if keys is not None else get_settings().secrets_key
    entries = [e for e in raw.split(",") if e.strip()]
    if not entries:
        raise RuntimeError("ARBITER_SECRETS_KEY is empty")
    return MultiFernet([Fernet(_key(e)) for e in entries])


def encrypt(plaintext: str, keys: str | None = None) -> str:
    return _fernet(keys).encrypt(plaintext.encode()).decode()


def decrypt(token: str, keys: str | None = None) -> str:
    try:
        return _fernet(keys).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretDecryptError("secret cannot be decrypted with the configured keys") from e


def rotate(token: str, keys: str | None = None) -> str:
    return _fernet(keys).rotate(token.encode()).decode()


def mask(secret: str) -> str:
    """For display: never more than the last 4 characters."""
    return f"****{secret[-4:]}" if len(secret) > 8 else "****"

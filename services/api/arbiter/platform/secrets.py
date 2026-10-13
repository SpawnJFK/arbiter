"""Encryption at rest for secrets kept in the database (SSO client secrets, engine keys D-056).

The single encryption helper of the platform; every module uses it.

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

from arbiter.config import Settings, get_settings

_HKDF_INFO = b"arbiter-secrets-v1"


class SecretsUnavailable(RuntimeError):
    """No usable key, or a stored value that no configured key can decrypt."""


class SecretDecryptError(SecretsUnavailable):
    """The ciphertext was not produced by any configured key (or was tampered with)."""


Keys = str | Settings | None


def _raw(keys: Keys) -> str:
    if keys is None:
        return get_settings().secrets_key
    if isinstance(keys, Settings):
        return keys.secrets_key
    return keys


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


def _fernet(keys: Keys = None) -> MultiFernet:
    entries = [e for e in _raw(keys).split(",") if e.strip()]
    if not entries:
        raise SecretsUnavailable("ARBITER_SECRETS_KEY is empty")
    return MultiFernet([Fernet(_key(e)) for e in entries])


def encrypt(plaintext: str, keys: Keys = None) -> str:
    return _fernet(keys).encrypt(plaintext.encode()).decode()


def decrypt(token: str, keys: Keys = None) -> str:
    try:
        return _fernet(keys).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretDecryptError("secret cannot be decrypted with the configured keys") from e


def rotate(token: str, keys: Keys = None) -> str:
    return _fernet(keys).rotate(token.encode()).decode()


def mask(secret: str) -> str:
    """For display: never more than the last 4 characters."""
    return f"****{secret[-4:]}" if len(secret) > 8 else "****"


def hint(secret: str) -> str:
    """What the engines UI may show after save: the last 4 characters, never more."""
    tail = secret.strip()[-4:]
    return f"...{tail}" if tail else ""

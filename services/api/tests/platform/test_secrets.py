"""Encryption at rest (ARBITER_SECRETS_KEY): round trip, rotation, tamper detection."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from arbiter.platform.secrets import SecretDecryptError, decrypt, encrypt, mask, rotate

PASSPHRASE = "a-long-passphrase-for-the-test-suite-only"


def test_round_trip_with_passphrase_and_fernet_key():
    tok = encrypt("client-secret", PASSPHRASE)
    assert "client-secret" not in tok and decrypt(tok, PASSPHRASE) == "client-secret"
    key = Fernet.generate_key().decode()
    assert decrypt(encrypt("x", key), key) == "x"
    assert decrypt(encrypt("default"), None) == "default"  # settings key


def test_rotation_old_key_still_decrypts_and_rotate_moves_to_new():
    old = PASSPHRASE
    new = Fernet.generate_key().decode()
    tok = encrypt("s", old)
    both = f"{new},{old}"
    assert decrypt(tok, both) == "s"
    moved = rotate(tok, both)
    assert decrypt(moved, new) == "s"
    with pytest.raises(SecretDecryptError):
        decrypt(moved, old)


def test_tampered_or_foreign_ciphertext_fails():
    tok = encrypt("s", PASSPHRASE)
    with pytest.raises(SecretDecryptError):
        decrypt(tok[:-4] + "AAAA", PASSPHRASE)
    with pytest.raises(SecretDecryptError):
        decrypt(tok, "another-passphrase-of-enough-length-000")


def test_mask():
    assert mask("abcdefghijkl") == "****ijkl" and mask("short") == "****"

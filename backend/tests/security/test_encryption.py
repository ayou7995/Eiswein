"""AES-256-GCM roundtrip + tamper detection tests."""

from __future__ import annotations

import os

import pytest

from app.security.encryption import CipherBundle, decrypt, encrypt
from app.security.exceptions import EncryptionError


def test_roundtrip_recovers_plaintext() -> None:
    key = os.urandom(32)
    plaintext = b"a schwab refresh token: ABC123"
    bundle = encrypt(plaintext, key)
    assert decrypt(bundle, key) == plaintext


def test_wrong_key_raises() -> None:
    key = os.urandom(32)
    other = os.urandom(32)
    bundle = encrypt(b"secret payload", key)
    with pytest.raises(EncryptionError):
        decrypt(bundle, other)


def test_tampered_ciphertext_detected() -> None:
    key = os.urandom(32)
    bundle = encrypt(b"secret payload", key)
    tampered = CipherBundle(
        ciphertext=bundle.ciphertext[:-1] + bytes([bundle.ciphertext[-1] ^ 1]),
        nonce=bundle.nonce,
        tag=bundle.tag,
    )
    with pytest.raises(EncryptionError):
        decrypt(tampered, key)


def test_tampered_tag_detected() -> None:
    key = os.urandom(32)
    bundle = encrypt(b"secret payload", key)
    tampered = CipherBundle(
        ciphertext=bundle.ciphertext,
        nonce=bundle.nonce,
        tag=bytes(16),
    )
    with pytest.raises(EncryptionError):
        decrypt(tampered, key)


def test_wrong_key_length_raises() -> None:
    with pytest.raises(EncryptionError):
        encrypt(b"x", os.urandom(16))
    with pytest.raises(EncryptionError):
        decrypt(
            CipherBundle(ciphertext=b"x", nonce=os.urandom(12), tag=os.urandom(16)),
            os.urandom(24),
        )


def test_fresh_nonce_per_call() -> None:
    key = os.urandom(32)
    a = encrypt(b"payload", key)
    b = encrypt(b"payload", key)
    assert a.nonce != b.nonce
    assert a.ciphertext != b.ciphertext

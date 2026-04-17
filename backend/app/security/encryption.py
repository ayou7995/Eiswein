"""AES-256-GCM column-level encryption for broker credentials.

Used by `BrokerCredential.encrypted_refresh_token` (see db/models.py).
Schwab refresh tokens are the only secrets currently stored in the DB;
future credentials use the same primitive.

Returns a `CipherBundle` (ciphertext, nonce, tag) per decision E. The
32-byte key comes from `Settings.encryption_key_bytes()`.

Security notes
--------------
* AES-GCM authenticates ciphertext — tampering raises `EncryptionError`.
* A fresh 12-byte nonce is generated per encryption; nonce reuse with
  the same key is catastrophic for GCM, so never supply one manually.
* `cryptography.hazmat.primitives.ciphers.aead.AESGCM` wraps the tag
  into the ciphertext tail (16 bytes). We split it explicitly so the
  tag column exists for future migration if we swap libraries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.security.exceptions import EncryptionError

_NONCE_BYTES = 12
_TAG_BYTES = 16
_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class CipherBundle:
    """Immutable ciphertext artifact — ciphertext, nonce, tag."""

    ciphertext: bytes
    nonce: bytes
    tag: bytes


def encrypt(plaintext: bytes, key: bytes) -> CipherBundle:
    if len(key) != _KEY_BYTES:
        msg = f"AES-256-GCM key must be {_KEY_BYTES} bytes"
        raise EncryptionError(msg)
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    combined = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    ciphertext, tag = combined[:-_TAG_BYTES], combined[-_TAG_BYTES:]
    return CipherBundle(ciphertext=ciphertext, nonce=nonce, tag=tag)


def decrypt(bundle: CipherBundle, key: bytes) -> bytes:
    if len(key) != _KEY_BYTES:
        msg = f"AES-256-GCM key must be {_KEY_BYTES} bytes"
        raise EncryptionError(msg)
    if len(bundle.nonce) != _NONCE_BYTES:
        raise EncryptionError("nonce must be 12 bytes for AES-GCM")
    if len(bundle.tag) != _TAG_BYTES:
        raise EncryptionError("tag must be 16 bytes for AES-GCM")
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(
            bundle.nonce,
            bundle.ciphertext + bundle.tag,
            associated_data=None,
        )
    except InvalidTag as exc:
        raise EncryptionError("ciphertext authentication failed") from exc

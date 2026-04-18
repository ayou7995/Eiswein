#!/usr/bin/env python3
"""Rotate JWT_SECRET and/or ENCRYPTION_KEY (I21).

Because ENCRYPTION_KEY protects stored broker refresh tokens, its
rotation re-encrypts every row of `broker_credentials` in a single
transaction using the OLD key to decrypt and the NEW key to encrypt.

JWT_SECRET rotation simply invalidates every active session (users
must re-login). No DB mutation needed.

Usage:
    python scripts/rotate_secrets.py --db /srv/eiswein/data/eiswein.db \\
        --old-encryption-key "$OLD_ENC" --new-encryption-key "$NEW_ENC"

Either/both key flags may be omitted. The caller is responsible for
writing the NEW key values into the SOPS secrets file after this
script exits zero.
"""

from __future__ import annotations

import argparse
import base64
import os
import sqlite3
import sys

_TAG_BYTES = 16


def _decode_key(value: str, *, name: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"{name} must be base64-url encoded: {exc}") from exc
    if len(raw) != 32:
        raise SystemExit(f"{name} must decode to 32 bytes (got {len(raw)})")
    return raw


def _re_encrypt_broker_rows(db_path: str, old_key: bytes, new_key: bytes) -> int:
    # Import lazily so JWT-only rotations don't need cryptography.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    old = AESGCM(old_key)
    new = AESGCM(new_key)
    touched = 0
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        rows = conn.execute(
            "SELECT id, encrypted_refresh_token, token_nonce, token_tag " "FROM broker_credentials"
        ).fetchall()
        for row_id, ciphertext, nonce, tag in rows:
            plaintext = old.decrypt(nonce, ciphertext + tag, None)
            new_nonce = os.urandom(12)
            combined = new.encrypt(new_nonce, plaintext, None)
            new_ct, new_tag = combined[:-_TAG_BYTES], combined[-_TAG_BYTES:]
            conn.execute(
                "UPDATE broker_credentials "
                "SET encrypted_refresh_token=?, token_nonce=?, token_tag=? "
                "WHERE id=?",
                (new_ct, new_nonce, new_tag, row_id),
            )
            touched += 1
        conn.commit()
    return touched


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate JWT_SECRET / ENCRYPTION_KEY")
    parser.add_argument("--db", help="SQLite DB path (required when rotating encryption key)")
    parser.add_argument("--old-encryption-key")
    parser.add_argument("--new-encryption-key")
    parser.add_argument(
        "--rotate-jwt",
        action="store_true",
        help="Indicate JWT_SECRET rotation happened. "
        "This prints a reminder; value lives in SOPS.",
    )
    args = parser.parse_args()

    if args.rotate_jwt:
        print(
            "JWT_SECRET rotation acknowledged. All active sessions will be invalidated "
            "once the new value is deployed via SOPS."
        )

    if args.old_encryption_key or args.new_encryption_key:
        if not (args.old_encryption_key and args.new_encryption_key):
            print("Both --old-encryption-key and --new-encryption-key required.", file=sys.stderr)
            return 2
        if not args.db:
            print("--db required when rotating encryption key", file=sys.stderr)
            return 2
        old = _decode_key(args.old_encryption_key, name="--old-encryption-key")
        new = _decode_key(args.new_encryption_key, name="--new-encryption-key")
        touched = _re_encrypt_broker_rows(args.db, old, new)
        print(f"Re-encrypted {touched} broker_credential rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

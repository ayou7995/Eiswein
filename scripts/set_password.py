#!/usr/bin/env python3
"""Interactive ADMIN_PASSWORD_HASH generator.

Usage:
    python scripts/set_password.py

Prompts twice for a password, validates via zxcvbn (strong passphrase or
>=16 chars), and prints a bcrypt-12 hash. Paste the hash into `.env` or
the SOPS-encrypted secret file.

This is deliberately a standalone script — no FastAPI import — so it
runs on a VM without needing the app installed.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt
from zxcvbn import zxcvbn

MIN_LEN = 16
MIN_SCORE = 3


def _prompt_password() -> str:
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Confirm new password: ")
    if first != second:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(2)
    if len(first) < MIN_LEN:
        print(
            f"Password must be at least {MIN_LEN} characters (or use a passphrase).",
            file=sys.stderr,
        )
        sys.exit(2)
    strength = zxcvbn(first)
    if int(strength.get("score", 0)) < MIN_SCORE:
        feedback = strength.get("feedback", {})
        warning = feedback.get("warning") or "password is too guessable"
        suggestions = feedback.get("suggestions") or []
        print(f"Weak password: {warning}", file=sys.stderr)
        for line in suggestions:
            print(f"  - {line}", file=sys.stderr)
        sys.exit(2)
    return first


def main() -> int:
    password = _prompt_password()
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    print(hashed.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

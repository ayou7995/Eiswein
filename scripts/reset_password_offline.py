#!/usr/bin/env python3
"""Reset admin password directly against the SQLite file.

Runs on the VM without starting the FastAPI app. SSH key == identity
proof (I3). Documented in docs/OPERATIONS.md.

Usage:
    python scripts/reset_password_offline.py --db /srv/eiswein/data/eiswein.db --username admin

Steps
-----
1. Open the SQLite DB file directly with stdlib `sqlite3`.
2. Prompt twice for a new password.
3. Validate zxcvbn strength (mirrors `set_password.py`).
4. bcrypt-hash and UPDATE users.password_hash + reset lockout counters.
5. Append an audit_log row so the reset is recorded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import sqlite3
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
    score = int(zxcvbn(first).get("score", 0))
    if score < MIN_SCORE:
        print("Weak password — try a passphrase.", file=sys.stderr)
        sys.exit(2)
    return first


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline admin password reset")
    parser.add_argument("--db", required=True, help="Path to eiswein.db")
    parser.add_argument("--username", required=True, help="Username to reset")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    password = _prompt_password()
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    now_iso = dt.datetime.now(dt.UTC).isoformat()

    with sqlite3.connect(args.db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (args.username,),
        )
        row = cur.fetchone()
        if row is None:
            print(f"User not found: {args.username}", file=sys.stderr)
            return 3
        user_id = int(row[0])
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                failed_login_count = 0,
                locked_until = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (hashed, now_iso, user_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (timestamp, event_type, user_id, ip, user_agent, details)
            VALUES (?, ?, ?, NULL, NULL, ?)
            """,
            (now_iso, "password.reset_offline", user_id, json.dumps({"via": "script"})),
        )
        conn.commit()
    print(f"Password updated for user: {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

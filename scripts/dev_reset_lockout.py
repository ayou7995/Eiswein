"""Dev helper: clear login-failure audit rows to reset IP lockout.

Run this while iterating locally when the app-level 5-fail-in-15-min
lockout kicks in during manual testing. Safe to run without stopping
the backend.

NOT for production use. Refuses to run when ENVIRONMENT=production.

Usage:
    python scripts/dev_reset_lockout.py                # clear all login failures
    python scripts/dev_reset_lockout.py --all          # also clear successes
    python scripts/dev_reset_lockout.py --ip 127.0.0.1 # only the given IP
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import urllib.parse
from pathlib import Path

_LOGIN_FAILURE = "login.failure"
_LOGIN_LOCKOUT = "login.lockout"
_LOGIN_SUCCESS = "login.success"


def _resolve_db_path() -> Path:
    url = os.environ.get("DATABASE_URL", "sqlite:///./data/eiswein.db")
    if not url.startswith("sqlite:///"):
        raise SystemExit(f"Only SQLite URLs are supported here, got: {url}")
    # sqlite:///./data/eiswein.db -> ./data/eiswein.db
    # sqlite:////abs/path/eiswein.db -> /abs/path/eiswein.db
    path_part = url.removeprefix("sqlite:///")
    return Path(urllib.parse.unquote(path_part)).expanduser().resolve()


def main() -> int:
    if os.environ.get("ENVIRONMENT") == "production":
        print("Refusing to run in production.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", help="Only clear rows for this IP.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also delete LOGIN_SUCCESS rows (default: only failures + lockouts).",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    events = [_LOGIN_FAILURE, _LOGIN_LOCKOUT]
    if args.all:
        events.append(_LOGIN_SUCCESS)

    placeholders = ",".join("?" * len(events))
    where = f"event_type IN ({placeholders})"
    params: list[object] = list(events)
    if args.ip:
        where += " AND ip = ?"
        params.append(args.ip)

    # The `where` clause is built from constants (_LOGIN_FAILURE /
    # _LOGIN_LOCKOUT / _LOGIN_SUCCESS) and a fixed `ip` column match, all
    # with bound `params`. No user-controlled string reaches the SQL text.
    count_sql = f"SELECT COUNT(*) FROM audit_log WHERE {where}"  # noqa: S608
    delete_sql = f"DELETE FROM audit_log WHERE {where}"  # noqa: S608
    with sqlite3.connect(db_path) as conn:
        before = conn.execute(count_sql, params).fetchone()[0]
        conn.execute(delete_sql, params)
        conn.commit()

    print(f"Deleted {before} audit row(s) matching {events}", end="")
    if args.ip:
        print(f" for ip={args.ip}", end="")
    print(f" from {db_path}.")
    print("Restart the backend to also clear slowapi's in-memory counter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

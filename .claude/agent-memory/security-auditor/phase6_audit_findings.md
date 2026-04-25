---
name: Phase 6 Audit Findings
description: Security findings from Phase 6 audit (APScheduler, email, backup, vacuum, system_metadata)
type: project
---

Phase 6 audit result: 0 CRITICAL, 1 HIGH, 2 MEDIUM.

**Why:** Phase 6 added APScheduler cron jobs, SMTP email dispatch via Jinja2, SQLite backup with rotation, and system_metadata KV table.

**How to apply:** Future audits of these modules can skip re-checking the items marked clean below.

## CRITICAL: All clean
- Jinja2 autoescape: `select_autoescape(enabled_extensions=("html",), default=True)` — `default=True` means ALL templates get autoescaped regardless of extension. Both templates are `.html` anyway. No `| safe`, `Markup()`, or `{% raw %}` on DB-supplied strings.
- SMTP_PASSWORD: stored as SecretStr, accessed only via `.get_secret_value()` at login call, never logged.
- Backup row-count: `_verify_backup()` runs `PRAGMA integrity_check` + `COUNT(*)` on users/watchlist/daily_signal tables.
- Scheduler lock: `_DEFAULT_LOCK_PATH = Path("data/scheduler.lock")` — hardcoded, no user input in any job file path.
- No command injection, no path traversal, no SQL injection in new code.

## HIGH (1 finding)
- Backup file permissions: `_atomic_backup()` in `backup.py` creates files via `sqlite3.connect(str(tmp))` with no chmod/umask call. Backup DB files containing bcrypt hashes + encrypted Schwab tokens inherit the process umask (typically 022 = world-readable). Fix: set `os.chmod(target, 0o600)` after `tmp.replace(destination)`.

## MEDIUM (2 findings)
- SMTP exception `str(exc)` in `_dispatch()` log (email_dispatcher.py:354): `smtplib.SMTPAuthenticationError` may embed the server's response message in `str(exc)`, which some SMTP servers include the username in. Low risk (structlog not shipped to client) but note for log hygiene — log `error_type` only and drop the `error=str(exc)` field for SMTP auth failures.
- python-jose 3.3.0 + ecdsa 0.19.2 are pinned dependencies with known CVEs (CVE-2024-33664, CVE-2024-33663 for python-jose; timing oracle in ecdsa). Not new to Phase 6 but flagged for follow-up.

## False positives for Phase 6
- `f"file:{source}?mode=ro"` in backup.py: `source` is always derived from `engine.url.database` (config), never user input. Safe.
- `f"SELECT COUNT(*) FROM {table}"` in `_verify_backup()`: `table` comes from the hardcoded `_VERIFY_TABLES` tuple, not user input. noqa: S608 comment is correct.
- health endpoint `fred: "not_configured"` — emits boolean status only, does not leak the FRED key value.
- system_metadata writes are all from job code using well-known constant keys — no user-controlled input reaches `SystemMetadataRepository.set()`.

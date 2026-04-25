---
name: Project Security Baseline
description: Core security architecture of Eiswein — auth layers, secrets, threat model
type: project
---

Eiswein security stack (as of 2026-04-22):
- Outer auth: Cloudflare Tunnel + Cloudflare Access (OAuth). No public ports.
- Inner auth: JWT in httpOnly, SameSite=Lax, Secure cookie (never localStorage).
- Single-user: one admin. No RBAC yet; all auth checks are `current_user_id` (JWT validity).
- Rate limiting: slowapi keyed by `CF-Connecting-IP` via `ClientIPMiddleware`.
- Secrets: SOPS + age encrypted. Age key at `/etc/eiswein/age.key` (chmod 600).
- Schwab refresh tokens: AES-256-GCM column-level encryption in `BrokerCredential`.
- Database: SQLite WAL mode. ORM-only (SQLAlchemy). No raw SQL strings.
- Log sanitizer: structlog processor redacts keys matching `/password|token|secret|key/i`.
  NOTE: The sanitizer is KEY-NAME based only — exception messages embedded in the `error`
  log field are NOT scrubbed for symbol names or PII in the values.

**Why:** Internet-facing cloud VM with financial data + brokerage API access = high-value target.
**How to apply:** Every new endpoint must have `current_user_id` Depends. Every sensitive value
must be under a redacted key name, or sanitized before logging.

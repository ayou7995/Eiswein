---
name: Accepted Patterns (false-positive register)
description: Patterns that look suspicious but are verified safe in this codebase
type: feedback
---

## `symbols_as_of` + `distinct_symbols_across_users` — no user_id filter
Both methods in `WatchlistRepository` intentionally omit `user_id` filtering.
`symbols_as_of` is used by the backfill orchestrator and daily_update to build the
cross-user union of symbols for a given date. This is correct: the single-admin owns
all watchlist entries; the method's docstring explicitly states "DISTINCT across users."
Do NOT flag as a missing auth scope check.

## `localStorage` key `eiswein.backfill.jobId`
Stores only an integer job ID. No tokens, credentials, or PII. Safe.

## `BackfillConfirmModal` typed-confirmation "BACKFILL"
Client-side UX friction only — correctly does NOT send a confirmation token to the backend.
Backend `/start` endpoint enforces auth + rate limit + active-job check, which is the real
guard. Do not flag the modal's confirm step as a missing backend control.

## `force=True` deletes live rows without a separate backend token
The brief confirms this is intentional. The two-layer UI (plan preview + typed confirmation)
is the intended UX guard. Backend deletes live rows when `force=True` — this is "working as
designed." Flag as a NOTE in future audits, not a finding.

## `get_active()` check + `create()` are not DB-atomic
SQLite WAL mode with `uvicorn --workers 1` means there is only one writer process, making
the check-then-create pair functionally atomic in production. Rate limit of 1/min + single
worker means the TOCTOU window is negligible. Accepted for single-process deployment.

## `_acquire_lock_blocking` uses `LOCK_EX` (blocking)
The blocking flock is a feature: backfill waits for nightly daily_update to finish.
Max lock duration for a 5-year range is bounded (see findings for estimate). Accepted.

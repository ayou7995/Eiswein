---
name: Accepted Patterns (false-positive register)
description: Patterns that look suspicious but are verified safe in this codebase
type: feedback
---

## `distinct_symbols_across_users` — no user_id filter
`WatchlistRepository.distinct_symbols_across_users` intentionally omits `user_id`
filtering. Used by backfill + daily_update to build the cross-user union of symbols.
Single-admin owns all watchlist entries; the method's docstring explicitly states
"DISTINCT across users." Do NOT flag as a missing auth scope check.

## `force=True` deletes existing rows without a separate backend token
The brief confirms this is intentional. The two-layer UI (plan preview + typed confirmation)
is the intended UX guard. Backend deletes existing rows when `force=True` — this is "working as
designed." Flag as a NOTE in future audits, not a finding.

## `get_active()` check + `create()` are not DB-atomic
SQLite WAL mode with `uvicorn --workers 1` means there is only one writer process, making
the check-then-create pair functionally atomic in production. Rate limit of 1/min + single
worker means the TOCTOU window is negligible. Accepted for single-process deployment.

## `snapshot_write_mutex` uses a blocking `threading.Lock`
`SnapshotWriteMutex` (in `app/services/snapshot_write_mutex.py`) wraps a
`threading.Lock` so backfill, onboarding, and daily_update serialize their
snapshot-write phases inside the single uvicorn worker. Blocking is intentional —
callers wait their turn rather than fail. Accepted.

Scheduler-level dedup is a separate, non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)`
on `data/scheduler.lock` (see `app/jobs/scheduler.py::_try_acquire_lock`); it's a
belt-and-suspenders for the `--workers 1` invariant and refuses to start if held.

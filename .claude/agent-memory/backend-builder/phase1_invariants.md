---
name: Phase 1 Invariants Implemented
description: Maps the four production invariants (cold-start, WAL, yfinance bulk, scheduler lock) and the per-symbol lock to concrete Phase 1 files.
type: project
---

# Phase 1 invariants map

| Invariant | Location |
|---|---|
| Cold start with 5s timeout + 202 fallback | `backend/app/api/v1/watchlist_routes.py::add_to_watchlist` (uses `_COLD_START_BUDGET_SECONDS`, `BackgroundTasks`) |
| WAL via event listener (not connect_args) | Already in Phase 0 `backend/app/db/database.py::apply_sqlite_pragmas`; Phase 1 adds no new connect-time behavior |
| ONE yfinance bulk call per daily_update | `backend/app/datasources/yfinance_source.py::_download_with_retry` + `backend/app/ingestion/daily_ingestion.py::run_daily_update` (single `data_source.bulk_download(distinct_symbols)` call) |
| APScheduler file lock | Phase 6 — not yet |
| Per-symbol `asyncio.Lock` for cold-start | `backend/app/ingestion/locks.py` (module-level dict + registry guard, `reset_locks_for_tests` for test isolation) |
| Parquet cache + 7-day eviction | `backend/app/datasources/yfinance_source.py::find_and_remove_old_parquets` (called at start of every `bulk_download`) |
| Market calendar check | `backend/app/ingestion/market_calendar.py::is_trading_day_et` (wrapped so tests monkeypatch cleanly) |
| Delisted ticker UX | `backfill_ticker` → `DataSourceError(reason="delisted_or_invalid")` + sets `watchlist.data_status="delisted"` |

## Gotcha: which errors propagate from `backfill_ticker`

- `NotFoundError` — row was deleted between cold-start trigger and task run (background path only; route path validates up front)
- `DataSourceError` — empty frame (delisted) OR upstream failure; both surface the same exception, but the `data_status` differs (`delisted` vs `failed`)
- Route wraps in try/except and always returns a `WatchlistItem` reflecting the post-backfill `data_status`

## Session lifecycle in cold-start

Route:
1. `repo.add(...)` inserts pending row
2. `session.commit()` — row persists even if timeout fires
3. `asyncio.timeout(5)` wraps `backfill_ticker`
4. `backfill_ticker` does its own `db.commit()` after UPSERT + status update
5. Route `session.refresh(row)` to see final status
6. Route returns, FastAPI's `get_db_session` commits one more time (no-op)

On timeout: background task opens its own `factory()` session, duplicates the pattern, and closes cleanly.

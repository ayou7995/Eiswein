---
name: Phase 1 Audit Findings
description: Issues found and verified-clean checks from the Phase 1 (data layer + ingestion + cold-start API) audit on 2026-04-17
type: project
---

## Findings (to fix)

### HIGH
1. `DataSourceError.details` leaked to client in `/api/v1/watchlist` cold-start path — `exc.details` dict (which may contain raw upstream error strings from yfinance/FRED) is passed into `WatchlistCreateResponse` indirectly via the row status. Actually the main risk is `yfinance_source.py:134` wraps raw exc string into DataSourceError.details, and error_handlers.py:40 returns that in the JSON envelope to the client. For DataSourceError (502), the `details` dict with `{"reason": "upstream_error", "error": str(exc)}` is returned verbatim in the HTTP response body.

2. `raise exc` in background task (watchlist_routes.py:282) re-raises into the background task runner where it will be silently swallowed — this is a non-issue for security but worth noting as a behavioral bug (the raise does nothing useful in a BackgroundTasks runner).

### MEDIUM
1. Watchlist cap TOCTOU: `count_for_user` + `add` are two separate ORM calls without a DB-level transaction isolation guarantee (SQLite default serializable, so this is safe in practice with --workers 1, but worth noting).
2. Lock dict grows unbounded — no eviction for removed tickers. Acceptable for <100 tickers.

## Verified Clean (Phase 1)
- yfinance ONE bulk call invariant: confirmed in `_download_with_retry`, `threads=False` set
- Parquet cache path: hash-only filename, no user input in path construction
- Retry exhaustion wraps in DataSourceError envelope
- SchwabSource + PolygonSource: all data methods raise NotImplementedError
- Per-symbol lock normalization: `.upper()` applied in `get_symbol_lock`
- UPSERT correctness: ON CONFLICT targets match UniqueConstraint definitions
- Auth coverage: all new routes use `Depends(current_user_id)`
- Watchlist cap enforced BEFORE DB write in `repo.add()`
- Symbol validation: I17 regex applied on both POST body and path params
- Background task uses fresh session from `request.app.state.session_factory`
- Rate limit on `/data/refresh`: `@limiter.limit("1/hour")`
- Cross-user data leak: all queries filter by user_id from JWT, no user_id query param
- No raw HTTPException in new routes
- FRED_API_KEY: SecretStr, never logged (key name matches redactor pattern "key")
- DB schema: Watchlist.user_id CASCADE on delete, DailyPrice has no user FK
- Decimal Numeric(12,4) for prices — no float

**Why:** Recorded to avoid redundant re-checks in Phase 2+ audits.
**How to apply:** Only re-check these if the relevant files change.

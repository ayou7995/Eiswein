---
name: Phase 3 Audit Findings
description: Issues found and verified-clean checks from the Phase 3 (signal composition layer + TickerSnapshot/MarketSnapshot + market/ticker signal APIs) audit on 2026-04-17
type: project
---

## Findings

### HIGH
1. `NotFoundError.details` in ticker_routes.py and market_routes.py passes raw dict values verbatim to the client via `eiswein_error_handler`. The `{"symbol": validated}` shape in ticker 404s is low-risk (symbol is already user-supplied input), but the `{"reason": "no_signal_composed"}` string leaks internal job-state language. The Phase 1 HIGH finding about DataSourceError.details leaking upstream errors is the same root pattern — same fix (strip or whitelist detail values) should apply here too.

2. `_coerce_signal` in ticker_routes.py:125 uses `# type: ignore[return-value]` to bypass the type checker. This is a "lie to mypy" pattern that suppresses strict-mode guarantees and masks the fact that the return type `SignalToneLiteral` is not enforced at runtime. The correct fix is a proper cast or a discriminated union.

### MEDIUM
1. `compose_and_persist_market` in ingestion/signals.py calls `MarketSnapshotRepository.upsert()` and `MarketPostureStreakRepository.record_posture()` sequentially but no explicit transaction scope wraps both operations. If the streak UPSERT raises after the snapshot UPSERT flushes, the session's outer `db.commit()` in `_compute_and_compose_for_all` at line 307 still commits the snapshot without a streak row. The outer `except Exception` in daily_ingestion.py:256 wraps both calls together, which means a partial flush of the snapshot without the streak CAN be committed when the outer commit runs — only the exception on the streak would need to escape the try/except at line 251-261 for this to materialize. In practice, this is low-probability but the invariant "snapshot and streak are always co-written on the same day" is not enforced at the DB layer.

2. `ProsConsItemResponse.detail` in both market_routes.py and ticker_routes.py is typed as `dict[str, object]` and passed through verbatim from `IndicatorResult.detail`. When the indicator fails, `detail` contains `{"error_class": "ValueError"}` — this is the error_class-only shape locked in Phase 2 as acceptable. However, for non-error indicators, detail can contain arbitrary numerics from individual indicator modules. There is no allowlist on which detail keys surface in the API, so a future indicator that accidentally includes a sensitive internal value (e.g., raw DataFrame shape, file path fragment) would silently leak. Low risk now, but no structural guard.

## Verified Clean (Phase 3)

### Signal purity
- ZERO network/DB imports in app/signals/*: confirmed — no requests/httpx/urllib/yfinance/fredapi/sqlalchemy imports in direction.py, timing.py, market_posture.py, compose.py, entry_price.py, stop_loss.py, pros_cons.py, types.py, labels.py
- No indicator re-computation: signals layer reads pre-classified IndicatorResult dicts, never calls indicator modules directly
- decision table (direction.py): implemented as `_DIRECTION_TABLE` tuple of 6 rows scanned in order — zero if/elif chains
- pros_cons.py: strict category mapping only. `short_label` passes through verbatim. Zero string concatenation forming sentences.

### Data model
- TickerSnapshot: UNIQUE(symbol, date) + `sqlite_insert().on_conflict_do_update()` — ORM UPSERT, no raw SQL
- MarketSnapshot: UNIQUE(date) — confirmed via `unique=True` on date column
- Streak repo: `_get_previous` uses strict `< before` comparison (not ≤) to prevent same-day stacking on idempotent re-runs. Advance vs reset logic correct.
- Alembic 0004 downgrade: drops market_posture_streak → market_snapshot (+ indexes) → ticker_snapshot (+ indexes). FK order correct (no FK dependencies between Phase 3 tables).

### API
- `/api/v1/market-posture`: `_user_id: int = Depends(current_user_id)` present — auth required
- `/api/v1/ticker/{symbol}/signal`: `user_id: int = Depends(current_user_id)` present — auth required
- Cross-user isolation: ticker signal route calls `watchlist.get(user_id=user_id, symbol=validated)` before reading TickerSnapshot — user A cannot read user B's ticker signal (even though TickerSnapshot is shared global data, the watchlist ownership check gates the response)
- Path param validation: both routes call `validate_symbol_or_raise(symbol)` — I17 regex applied
- ComposedSignalResponse: no internal DB `id`, no `user_id`, no FK exposed — clean wire shape
- `detail` in ProsConsItemResponse: contains only `error_class` on failures (Phase 2 locked) — no full exception messages reach the client

### Enum persistence
- `composed_to_row()` in ticker_snapshot_repository.py: all enum fields use `.value` explicitly (action.value, timing_modifier.value, market_posture_at_compute.value)
- `build_market_snapshot_row()`: posture.value used
- `record_posture()`: posture.value used — no raw enum objects reach DB

### Numeric safety
- TickerSnapshot entry/stop columns: Numeric(14,4) — matches Decimal domain type
- `_quantize()` uses `Decimal(str(value))` (not `Decimal(value)`) to avoid binary-float trap
- `_healthy_stop`: guards `len(close) < 200` before sma(200) — no ZeroDivisionError path
- `_weakening_stop`: guards `tail.empty` before `tail.min()` — no ZeroDivisionError on empty frame

### No template narrator
- No f-string sentence construction found in app/signals/* — grep for `f".*{` pattern returned zero matches
- `posture_streak_badge()` in labels.py uses f-string `f"進攻 {streak_days} 天 ✨"` — this is a badge string with one numeric interpolation, NOT a prose narrator. Safe.

### Integration with daily_update
- Per-ticker compose wrapped in `try/except Exception` at daily_ingestion.py:289-305 — one failure does not kill the batch
- MarketSnapshot written via UPSERT — idempotent on repeat invocation of daily_update
- `effective_posture = market_posture or MarketPosture.NORMAL` — if market compose fails, tickers default to NORMAL posture (conservative, not None)
- Error envelope: all Phase 3 routes use `NotFoundError` (EisweinError subclass) — no raw `HTTPException`
- `sanitize_validation_errors` still active in error_handlers.py — `ValueError` from field_validator cannot escape as raw JSON

**Why:** Recorded to avoid redundant re-checks in Phase 4+ audits.
**How to apply:** Only re-check these if the relevant files change.

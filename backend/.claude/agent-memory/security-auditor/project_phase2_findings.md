---
name: Phase 2 Audit Findings
description: Issues found and verified-clean checks from the Phase 2 (indicators engine + DailySignal + ticker API) audit on 2026-04-17
type: project
---

## Findings

### HIGH
1. `error_result()` propagates internal exception message strings into `DailySignal.detail` JSON and those are returned verbatim to the client via `GET /api/v1/ticker/{symbol}/indicators`. The `reason` field is `f"{type(exc).__name__}: {exc}"` — exception messages from numpy/pandas can include file paths, array shapes, or internal index values that constitute information leakage.

2. `IndicatorContext.spx_frame` is a `pd.DataFrame | None` field in a `frozen=True` dataclass. Python's `frozen=True` prevents reassignment of the field, but DataFrame contents are mutable in-place. Any indicator that calls `frame.iloc[...] = ...` or `frame.dropna(inplace=True)` on `context.spx_frame` would corrupt state shared across all per-ticker indicator calls in the same batch. Current code doesn't do this, but the contract is not enforced.

### MEDIUM
1. `_coerce_signal()` silently maps unknown stored signal strings to "neutral" — if the DB were ever corrupted or a future indicator version introduced a new tone, the mismatch would be invisible to the caller (no log, no metric). Low exploitability but a silent data integrity bypass.

2. `error_result` detail dict `{"error": reason}` stores exception text permanently in the database. This is a minor persistent information-leakage vector — exception messages are frozen in `DailySignal.detail` indefinitely.

## Verified Clean (Phase 2)
- Indicator purity: ZERO network imports (yfinance/requests/httpx/urllib/fredapi) in all 12 indicator modules
- DB imports: ZERO sqlalchemy/session imports in any indicator module — pure DataFrame → IndicatorResult
- DataFrame mutation: no `inplace=True` or `.loc[...] =` mutations in indicator modules; `ad_day.py` calls `.copy()` before any slice operations (correct)
- Orchestrator wraps ALL 12 indicators (both `_PER_TICKER` and `_MARKET_REGIME` loops) in `_safe_run` with double try/except
- Error catch scope: first except catches `(ValueError, TypeError, ArithmeticError, KeyError, IndexError)` — domain errors. Second catches `Exception` (catch-all for unexpected). Neither catches `SystemExit`/`KeyboardInterrupt` — config/auth errors would propagate naturally.
- DailySignal UPSERT: uses `sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_update()` — parameterized, no raw SQL strings
- UNIQUE constraint: `(symbol, date, indicator_name)` in model matches `index_elements` in UPSERT exactly
- Numpy/pandas scalar sanitization: ALL detail dict values use `float()`, `int()`, `bool()` casts before being stored — no raw `np.float64` / `np.bool_` scalars leak into the JSON detail dict
- Ticker indicator route auth: `user_id: int = Depends(current_user_id)` present
- Symbol path param validated: `validate_symbol_or_raise(symbol)` called (I17 regex via SymbolInput Pydantic model)
- Cross-user data leak: route checks `watchlist.get(user_id=user_id, symbol=validated)` — user must own the ticker; then indicator read is by symbol (shared global data — correct per A1 spec)
- Pydantic response model: `IndicatorResultResponse` has no internal DB fields (no `id`, no FK)
- Indicator-version column: persisted per-row, returned in response — historical rows keep their formula version
- Indicator compute ordering: `build_context()` reads from DB AFTER `db.commit()` on line 141+147 — context loads freshly committed price + macro data
- generate_indicator_fixtures.py: not yet implemented; only referenced in conftest.py comment and README. No risk of accidental CI import.
- requirements.in: no new Phase 2 additions beyond Phase 1 — indicators hand-rolled using existing numpy/pandas
- `pandas_ta` not added — confirmed absent

**Why:** Recorded to avoid redundant re-checks in Phase 3+ audits.
**How to apply:** Only re-check these if the relevant files change.

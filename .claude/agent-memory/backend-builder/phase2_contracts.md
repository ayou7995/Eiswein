---
name: Phase 2 Indicator Contracts
description: Indicator package layout, IndicatorResult shape, orchestrator registry, DailySignal repository + endpoint signatures used by Phase 3+.
type: project
---

# Phase 2 Module Contracts

## Public API of `app/indicators/`

- `IndicatorResult` (frozen Pydantic v2 BaseModel): `name, value, signal, data_sufficient, short_label, detail, computed_at, indicator_version`.
- `SignalToneLiteral = Literal["green", "yellow", "red", "neutral"]`.
- `SignalTone` static class with `Final[Literal[...]] = "..."` constants for GREEN/YELLOW/RED/NEUTRAL (used where a name is clearer than a string literal).
- `insufficient_result(name)` / `error_result(name, reason=...)` helpers — used by `_safe_run` in orchestrator.
- `INDICATOR_VERSION = "1.0.0"` (bump when formulas change; persisted per DailySignal row).
- `IndicatorContext(today, indicator_version, spx_frame, macro_frames)` — frozen dataclass passed to every compute function.

## Orchestrator registry

- `compute_all(symbol, price_frame, context) -> dict[str, IndicatorResult]` covers 8 per-ticker names: `price_vs_ma, rsi, volume_anomaly, relative_strength, macd, bollinger, dxy, fed_rate`.
- `compute_market_regime(context) -> dict[str, IndicatorResult]` covers 4 regime names: `spx_ma, ad_day, vix, yield_spread`.
- `_safe_run` wraps every call in try/except so one broken indicator returns an error_result NEUTRAL but does not abort the batch.

## DailySignal persistence

- Table: `daily_signal(id, symbol, date, indicator_name, signal, value, data_sufficient, short_label, detail JSON, indicator_version, computed_at)` with UNIQUE(symbol, date, indicator_name).
- Migration: `alembic/versions/0003_phase2_indicator_layer.py`.
- Repository: `DailySignalRepository(session)` with `upsert_many`, `get_latest_for_symbol`, `get_range`. `result_to_row(symbol, date, result)` converts in-memory IndicatorResult → UPSERT row.
- DI: `get_daily_signal_repository` in `api/dependencies.py`.

## API

- `GET /api/v1/ticker/{symbol}/indicators` — returns `{symbol, date, indicator_version, indicators: {name: IndicatorResultResponse}}`.
- Auth required. 404 if ticker not in user's watchlist OR no computed rows yet (error.details.reason differentiates).

## Ingestion hook

- `app/ingestion/indicators.py` provides `build_context`, `compute_and_persist`, `compute_and_persist_market_regime`.
- `daily_ingestion.run_daily_update` calls these AFTER price/macro UPSERT. `DailyUpdateResult` now has `indicators_computed_symbols` + `indicators_failed_symbols`.

## Implementation choices worth remembering

- Wilder RSI / MACD / Bollinger are hand-rolled in `app/indicators/_helpers.py` (pandas EWM + rolling). Did NOT add pandas_ta because its 0.3.14b0 release imports `numpy.NaN` (removed in numpy 2.x) and is abandoned.
- Bollinger uses `std(ddof=0)` (population) to match TradingView.
- DXY uses FRED DTWEXBGS as proxy (raw DXY not on FRED).
- RSI flat-series convention: 50.0 (both avg gain and avg loss == 0). Saturated-rising: 100.0.

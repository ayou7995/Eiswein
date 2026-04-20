---
name: Phase 3 Signal Layer Contracts
description: Signal composition package layout, ComposedSignal shape, snapshot repositories, market-posture + ticker-signal endpoint signatures used by Phase 4 dashboard.
type: project
---

# Phase 3 Module Contracts

## Public API of `app/signals/`

- Enums (all `str, Enum` so `.value` is the canonical DB string):
  - `ActionCategory`: `strong_buy|buy|hold|watch|reduce|exit`
  - `TimingModifier`: `favorable|mixed|unfavorable`
  - `MarketPosture`: `offensive|normal|defensive`
- `ProsConsItem(category, tone, short_label, detail, indicator_name)` — frozen dataclass w/ slots. Category literal = `direction|timing|macro|risk`. Tone literal = `pro|con|neutral`.
- `EntryTiers(aggressive, ideal, conservative, split_suggestion=(30,40,30))` frozen Pydantic model.
- `ComposedSignal(symbol, date, action, direction_green_count, direction_red_count, timing_modifier, show_timing_modifier, entry_tiers, stop_loss, market_posture_at_compute, indicator_version, computed_at)` frozen Pydantic model.
- Chinese labels: `ACTION_LABELS`, `TIMING_BADGES` (MIXED=None), `POSTURE_LABELS`, `posture_streak_badge(posture, days)` (None below 3, None for NORMAL always).

## Classifier signatures

- `classify_direction(results) -> (ActionCategory, green, red)` — D1a decision table `(min_g, max_g, min_r, max_r, action)` rows scanned top-to-bottom. All-insufficient → (WATCH, 0, 0).
- `classify_timing(results) -> TimingModifier` — both-G=FAVORABLE, both-R=UNFAVORABLE, else MIXED.
- `classify_market_posture(regime_results) -> MarketPosture` — ≥3G=OFFENSIVE, ≥2R=DEFENSIVE, else NORMAL.
- `count_regime_tones(regime_results) -> (g, r, y)` for MarketSnapshot denormalization.
- `should_show_timing(action) -> bool` — True only for buy-side (STRONG_BUY/BUY/HOLD).
- `compose_signal(**kwargs) -> ComposedSignal` — thin adapter, no decision logic.

## Tier / Stop-loss signatures

- `compute_entry_tiers(ticker_frame, *, timing_modifier) -> EntryTiers` — returns Decimals quantized to .0001 via ROUND_HALF_UP. Each tier degrades to None independently when MA history is insufficient.
- `compute_stop_loss(ticker_frame, *, direction_action) -> Decimal | None` — healthy trend (buy-side) → 200MA × 0.97; weakening → BB-lower × 0.97, falling back to min(last 5 lows) × 0.97. 0.97 = 3% buffer for wicks.

## Pros/Cons mapping (per indicator name)

- `price_vs_ma | rsi | volume_anomaly | relative_strength` → `direction`
- `macd | bollinger` → `timing`
- `dxy | fed_rate | spx_ma | ad_day | vix | yield_spread` → `macro`
- Tone: GREEN → pro, RED → con, YELLOW/NEUTRAL/insufficient → neutral.
- `build_pros_cons_items` NEVER stitches prose — passes short_label verbatim. Unknown names are skipped.

## DB schema (Alembic 0004)

- `ticker_snapshot` UNIQUE(symbol, date) — one composed row per ticker per day.
- `market_snapshot` UNIQUE(date) — one global row per day + denormalized `regime_{green,red,yellow}_count`.
- `market_posture_streak` UNIQUE(as_of_date) — consecutive-days streak tracking (D3).

## Repositories

- `TickerSnapshotRepository(session)`:
  - `upsert_many(rows: Iterable[TickerSnapshotRow])` — SQLite ON CONFLICT DO UPDATE on (symbol, date).
  - `get_latest_for_symbol(symbol) -> TickerSnapshot | None`.
  - `composed_to_row(signal)` module helper projects ComposedSignal → TypedDict row (uses `.value` on all enums).
- `MarketSnapshotRepository(session)`:
  - `upsert(row)` / `get_latest()` / `get_for_date(d)`.
  - `build_market_snapshot_row(...)` helper TypedDict constructor.
- `MarketPostureStreakRepository(session)`:
  - `record_posture(*, as_of_date, posture, computed_at)` — reads the row strictly `< as_of_date`, advances on match / resets on mismatch, UPSERTs today's row. Idempotent for same-day re-runs (strict `<`).
  - `get_latest()` / `get_for_date(d)`.

## Ingestion wiring

- `app/ingestion/signals.py`:
  - `compose_and_persist_ticker(symbol, trade_date, *, db, per_ticker_results, market_posture)` — uses already-in-memory IndicatorResult dict; reloads price frame for entry/stop-loss calc.
  - `compose_and_persist_market(trade_date, *, db, regime_results) -> MarketPosture` — classifies, upserts MarketSnapshot + advances streak, returns posture for reuse in per-ticker compose.
- `daily_ingestion.run_daily_update` now calls regime compose + per-ticker compose in order. `DailyUpdateResult` grows `snapshots_composed / snapshots_failed / market_posture` fields.

## API

- `GET /api/v1/market-posture` → MarketPostureResponse (date, posture, posture_label, regime_{green,red,yellow}_count, streak_days, streak_badge, pros_cons[], indicator_version, computed_at). 404 when no snapshot. Auth required but NOT user-filtered (posture is global per A1).
- `GET /api/v1/ticker/{symbol}/signal` → ComposedSignalResponse (symbol, date, action, action_label, direction_{green,red}_count, timing_modifier, timing_badge, show_timing_modifier, entry_tiers, stop_loss, market_posture_at_compute, pros_cons[], indicator_version, computed_at). 404 on no snapshot OR not-on-watchlist (watchlist ownership enforced).

## Implementation choices worth remembering

- Signal module NEVER imports `app.db.models` or runs DB I/O — pure domain logic. Persistence lives in `app.ingestion.signals` so the signal layer stays Clean-Architecture-compliant.
- Regime indicators are stored under symbol="SPY" in DailySignal (same carrier row set as SPX per-ticker indicators). Market-posture endpoint filters the set by REGIME_INDICATOR_NAMES so it only surfaces the 4 regime ones.
- `show_timing_modifier` flag is STORED in TickerSnapshot so historical rows composed under earlier rules keep their original display behaviour (A2 audit-ability principle).
- Enum enforcement at DB boundary: we use plain VARCHAR columns + `.value` serialization + `_coerce_{action,timing,posture}` readers with logger.warning fallback on drift. Avoids SQLite ENUM complexity while staying type-safe at the API boundary.
- app.signals.* added to the pandas-bridge mypy override block alongside app.indicators / app.ingestion (entry_price + stop_loss consume pandas Series).

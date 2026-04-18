---
name: Phase 1 Module Contracts
description: Signatures and boundaries of the Phase 1 data layer — DataSource ABC, repositories, ingestion entry points, API routes.
type: project
---

# Phase 1 contracts (Eiswein backend)

## DataSource (`backend/app/datasources/base.py`)

```python
class DataSource(ABC):
    @property
    def name(self) -> str: ...
    async def bulk_download(self, symbols: list[str], *, period: str = "2y") -> dict[str, pd.DataFrame]: ...
    async def get_index_data(self, symbol: str, *, period: str = "2y") -> pd.DataFrame: ...
    async def health_check(self) -> DataSourceHealth: ...
```

Every implementation MUST return DataFrames with lowercase columns `[open, high, low, close, volume]` and a tz-aware `DatetimeIndex` in `America/New_York`.

Concrete: `YFinanceSource` (v1), `FREDSource` (v1), `SchwabSource` + `PolygonSource` (stubs).

## Models (`backend/app/db/models.py`)

- `Watchlist(user_id, symbol, data_status, added_at, last_refresh_at)` — UNIQUE(user_id, symbol). `data_status ∈ {pending, ready, failed, delisted}`.
- `DailyPrice(symbol, date, open, high, low, close, volume)` — UNIQUE(symbol, date). Prices are `Decimal(Numeric(12,4))` — never float.
- `MacroIndicator(series_id, date, value)` — UNIQUE(series_id, date).

## Repositories

- `WatchlistRepository.add(user_id, symbol, max_size)` — raises `WatchlistFullError` / `DuplicateWatchlistEntryError`.
- `WatchlistRepository.set_status(user_id, symbol, status, mark_refreshed=False)`.
- `WatchlistRepository.distinct_symbols_across_users()` — for daily_update bulk fetch.
- `WatchlistRepository.list_all_for_symbol(symbol)` — per-user rows for same ticker (daily_update broadcast).
- `DailyPriceRepository.upsert_many(rows: Iterable[DailyPriceRow])` — SQLite `INSERT … ON CONFLICT DO UPDATE`.
- `MacroRepository.upsert_many(rows: Iterable[MacroRow])`.

## Ingestion

- `backfill_ticker(symbol, *, user_id, db, data_source, years=2, force=False) -> str` — cold-start. Uses per-symbol `asyncio.Lock`. Returns final `data_status`.
- `run_daily_update(*, db, data_source, settings) -> DailyUpdateResult` — nightly orchestrator. Market calendar gate + ONE bulk call.

## API routes (all under `/api/v1/`)

- `GET  /watchlist`                              — paginated list
- `POST /watchlist`                              — cold-start with 5s timeout → 200 or 202
- `DELETE /watchlist/{symbol}`                   — remove (preserves price history)
- `GET  /data/status`                            — provider health + ticker counts
- `POST /data/refresh`                           — manual daily_update, rate-limited 1/hour
- `GET  /ticker/{symbol}?only_status=1`          — lightweight poll during pending

All protected by `Depends(current_user_id)`.

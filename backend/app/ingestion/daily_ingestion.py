"""Nightly daily_update orchestrator (I6, I7).

Flow:
1. Market calendar gate — skip if today is not an NYSE session.
2. ONE bulk yfinance call for all distinct watchlist symbols.
3. UPSERT DailyPrice rows per symbol, with per-ticker try/except so
   one symbol failure doesn't abort the job (rule 14: graceful
   degradation).
4. FRED macro fetch (best-effort — failures log + continue).
5. UPSERT MacroIndicator rows.

Not tied to APScheduler — Phase 6 wires the scheduler trigger, this
function is what it calls.

The function is ``async`` and takes a Session and DataSource as
parameters so tests can inject fakes (rule 13: DI).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import pandas as pd
import structlog

from app.config import Settings
from app.datasources.base import DataSource
from app.datasources.fred_source import DEFAULT_SERIES_IDS, FREDSource
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.macro_repository import MacroRepository, MacroRow
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.locks import get_symbol_lock
from app.ingestion.market_calendar import is_trading_day_et, last_trading_day_et
from app.ingestion.persist import iter_daily_price_rows
from app.security.exceptions import DataSourceError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.daily")


@dataclass(frozen=True)
class DailyUpdateResult:
    """Summary returned by ``run_daily_update``. All counts are non-negative."""

    market_open: bool
    session_date: date
    symbols_requested: int
    symbols_succeeded: int
    symbols_failed: int
    symbols_delisted: int
    price_rows_upserted: int
    macro_rows_upserted: int
    macro_series_failed: int


async def run_daily_update(
    *,
    db: "Session",
    data_source: DataSource,
    settings: Settings,
) -> DailyUpdateResult:
    """Run the daily ingestion job once.

    Idempotent: safe to re-run the same day — UNIQUE constraints +
    UPSERT keep state stable (rule 12).
    """
    session_day = last_trading_day_et()
    if not is_trading_day_et():
        logger.info("daily_update_skipped_market_closed", date=str(session_day))
        return DailyUpdateResult(
            market_open=False,
            session_date=session_day,
            symbols_requested=0,
            symbols_succeeded=0,
            symbols_failed=0,
            symbols_delisted=0,
            price_rows_upserted=0,
            macro_rows_upserted=0,
            macro_series_failed=0,
        )

    watchlist = WatchlistRepository(db)
    prices = DailyPriceRepository(db)
    macro = MacroRepository(db)

    symbols = list(watchlist.distinct_symbols_across_users())
    logger.info("daily_update_start", symbols=len(symbols), date=str(session_day))

    price_rows_total = 0
    succeeded = 0
    failed = 0
    delisted = 0

    if symbols:
        try:
            bulk = await data_source.bulk_download(symbols, period="2y")
        except DataSourceError as exc:
            logger.warning("daily_update_bulk_failed", details=exc.details)
            bulk = {}

        for sym in symbols:
            frame = bulk.get(sym)
            try:
                upserted = await _persist_symbol(
                    sym, frame, prices=prices, watchlist=watchlist
                )
            except DataSourceError as exc:
                reason = exc.details.get("reason") if isinstance(exc.details, dict) else None
                if reason == "delisted_or_invalid":
                    delisted += 1
                else:
                    failed += 1
                continue
            except Exception as exc:
                failed += 1
                logger.warning(
                    "daily_update_symbol_failed",
                    symbol=sym,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                continue
            if upserted == 0:
                failed += 1
                continue
            price_rows_total += upserted
            succeeded += 1

        db.commit()

    macro_rows_total, macro_series_failed = await _ingest_macro(
        macro=macro,
        settings=settings,
    )
    db.commit()

    logger.info(
        "daily_update_complete",
        date=str(session_day),
        symbols_requested=len(symbols),
        symbols_succeeded=succeeded,
        symbols_failed=failed,
        symbols_delisted=delisted,
        price_rows=price_rows_total,
        macro_rows=macro_rows_total,
    )
    return DailyUpdateResult(
        market_open=True,
        session_date=session_day,
        symbols_requested=len(symbols),
        symbols_succeeded=succeeded,
        symbols_failed=failed,
        symbols_delisted=delisted,
        price_rows_upserted=price_rows_total,
        macro_rows_upserted=macro_rows_total,
        macro_series_failed=macro_series_failed,
    )


async def _persist_symbol(
    symbol: str,
    frame: pd.DataFrame | None,
    *,
    prices: DailyPriceRepository,
    watchlist: WatchlistRepository,
) -> int:
    """Persist + update watchlist rows for a single ticker.

    Acquires the per-symbol lock so a concurrent cold-start backfill
    for the same ticker doesn't race the daily job (even though daily
    should be the only writer at 06:30 ET, belt-and-suspenders).
    """
    lock = await get_symbol_lock(symbol)
    async with lock:
        if frame is None or frame.empty:
            _mark_watchlist_rows(
                watchlist, symbol=symbol, status="delisted", mark_refreshed=False
            )
            raise DataSourceError(
                details={"reason": "delisted_or_invalid", "symbol": symbol}
            )
        rows = list(iter_daily_price_rows(symbol, frame))
        upserted = prices.upsert_many(rows)
        _mark_watchlist_rows(
            watchlist, symbol=symbol, status="ready", mark_refreshed=True
        )
        return upserted


def _mark_watchlist_rows(
    watchlist: WatchlistRepository,
    *,
    symbol: str,
    status: str,
    mark_refreshed: bool,
) -> None:
    """Update ``data_status`` for every user that holds this symbol.

    ``distinct_symbols_across_users`` is aggregated — we need the
    per-user rows to update. The ticker is shared master data so every
    user's row lands on the same status.
    """
    now = datetime.now(UTC) if mark_refreshed else None
    for row in watchlist.list_all_for_symbol(symbol):
        row.data_status = status
        if now is not None:
            row.last_refresh_at = now


async def _ingest_macro(
    *,
    macro: MacroRepository,
    settings: Settings,
) -> tuple[int, int]:
    """Fetch default FRED series; log + continue on failure."""
    key = settings.fred_api_key
    if key is None or not key.get_secret_value():
        logger.info("daily_update_macro_skipped_no_key")
        return (0, 0)

    try:
        source = FREDSource(api_key=key.get_secret_value())
    except DataSourceError as exc:
        logger.warning("daily_update_macro_init_failed", details=exc.details)
        return (0, len(DEFAULT_SERIES_IDS))

    try:
        frames = await source.bulk_download(list(DEFAULT_SERIES_IDS))
    except DataSourceError as exc:
        logger.warning("daily_update_macro_bulk_failed", details=exc.details)
        return (0, len(DEFAULT_SERIES_IDS))

    total = 0
    failed = 0
    for series_id, frame in frames.items():
        if frame.empty:
            failed += 1
            continue
        rows: list[MacroRow] = []
        for idx, row in frame.iterrows():
            d = _to_date(idx)
            if d is None:
                continue
            try:
                value = Decimal(str(row["value"]))
            except (InvalidOperation, ValueError):
                continue
            rows.append(MacroRow(series_id=series_id.upper(), date=d, value=value))
        if not rows:
            failed += 1
            continue
        total += macro.upsert_many(rows)
    return (total, failed)


def _to_date(idx: object) -> date | None:
    if isinstance(idx, pd.Timestamp):
        return idx.date()
    if isinstance(idx, date):
        return idx
    try:
        return pd.Timestamp(idx).date()  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None

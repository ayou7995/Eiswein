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
from app.ingestion.indicators import (
    build_context,
    compute_and_persist,
    compute_and_persist_market_regime,
)
from app.ingestion.locks import get_symbol_lock
from app.ingestion.market_calendar import is_trading_day_et, last_trading_day_et
from app.ingestion.persist import iter_daily_price_rows
from app.ingestion.signals import (
    compose_and_persist_market,
    compose_and_persist_ticker,
)
from app.security.exceptions import DataSourceError
from app.signals.types import MarketPosture

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
    indicators_computed_symbols: int
    indicators_failed_symbols: int
    # Phase 3: composed TickerSnapshot + MarketSnapshot outcomes.
    snapshots_composed: int
    snapshots_failed: int
    market_posture: MarketPosture | None


async def run_daily_update(
    *,
    db: Session,
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
            indicators_computed_symbols=0,
            indicators_failed_symbols=0,
            snapshots_composed=0,
            snapshots_failed=0,
            market_posture=None,
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
                upserted = await _persist_symbol(sym, frame, prices=prices, watchlist=watchlist)
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

    # Phase 2: compute + persist indicators from the freshly-written
    # raw data. Each symbol compute is isolated so one broken ticker
    # doesn't abort the rest (rule 14). Market-regime indicators run
    # once against the SPX frame + macro series.
    # Phase 3: compose + persist signals using the already-in-memory
    # IndicatorResult dicts (avoids a DB round-trip).
    compute_outcome = _compute_and_compose_for_all(
        db=db,
        symbols=symbols,
        session_day=session_day,
    )

    logger.info(
        "daily_update_complete",
        date=str(session_day),
        symbols_requested=len(symbols),
        symbols_succeeded=succeeded,
        symbols_failed=failed,
        symbols_delisted=delisted,
        price_rows=price_rows_total,
        macro_rows=macro_rows_total,
        indicators_ok=compute_outcome.indicators_ok,
        indicators_failed=compute_outcome.indicators_failed,
        snapshots_composed=compute_outcome.snapshots_ok,
        snapshots_failed=compute_outcome.snapshots_failed,
        market_posture=(
            compute_outcome.market_posture.value
            if compute_outcome.market_posture is not None
            else None
        ),
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
        indicators_computed_symbols=compute_outcome.indicators_ok,
        indicators_failed_symbols=compute_outcome.indicators_failed,
        snapshots_composed=compute_outcome.snapshots_ok,
        snapshots_failed=compute_outcome.snapshots_failed,
        market_posture=compute_outcome.market_posture,
    )


@dataclass(frozen=True)
class _ComputeOutcome:
    """Internal tally for the combined indicator + signal compose pass."""

    indicators_ok: int
    indicators_failed: int
    snapshots_ok: int
    snapshots_failed: int
    market_posture: MarketPosture | None


def _compute_and_compose_for_all(
    *,
    db: Session,
    symbols: list[str],
    session_day: date,
) -> _ComputeOutcome:
    """Compute + persist indicators AND compose + persist signals.

    Order is significant:
    1. Market-regime indicators + :class:`MarketSnapshot` go first so
       each per-ticker compose can reference the current posture.
    2. Per-ticker indicators → per-ticker :class:`TickerSnapshot`.

    Every step is guarded — one broken ticker does not abort the rest
    (rule 14).
    """
    try:
        context = build_context(db=db, today=session_day)
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("indicator_context_build_failed", error=str(exc))
        return _ComputeOutcome(
            indicators_ok=0,
            indicators_failed=len(symbols),
            snapshots_ok=0,
            snapshots_failed=len(symbols),
            market_posture=None,
        )

    # Market regime indicators + posture first.
    market_posture: MarketPosture | None = None
    try:
        regime_results = compute_and_persist_market_regime(session_day, db=db, context=context)
        market_posture = compose_and_persist_market(
            session_day, db=db, regime_results=regime_results
        )
    except Exception as exc:
        logger.warning(
            "market_regime_compose_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        market_posture = None

    effective_posture = market_posture or MarketPosture.NORMAL

    ind_ok = 0
    ind_failed = 0
    snap_ok = 0
    snap_failed = 0
    for sym in symbols:
        try:
            results = compute_and_persist(sym, session_day, db=db, context=context)
        except Exception as exc:
            ind_failed += 1
            snap_failed += 1
            logger.warning(
                "indicator_persist_failed",
                symbol=sym,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            continue
        if not results:
            ind_failed += 1
            snap_failed += 1
            continue
        ind_ok += 1

        try:
            compose_and_persist_ticker(
                sym,
                session_day,
                db=db,
                per_ticker_results=results,
                market_posture=effective_posture,
            )
            snap_ok += 1
        except Exception as exc:
            snap_failed += 1
            logger.warning(
                "signal_compose_failed",
                symbol=sym,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    db.commit()
    return _ComputeOutcome(
        indicators_ok=ind_ok,
        indicators_failed=ind_failed,
        snapshots_ok=snap_ok,
        snapshots_failed=snap_failed,
        market_posture=market_posture,
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
            _mark_watchlist_rows(watchlist, symbol=symbol, status="delisted", mark_refreshed=False)
            raise DataSourceError(details={"reason": "delisted_or_invalid", "symbol": symbol})
        rows = list(iter_daily_price_rows(symbol, frame))
        upserted = prices.upsert_many(rows)
        _mark_watchlist_rows(watchlist, symbol=symbol, status="ready", mark_refreshed=True)
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
        return pd.Timestamp(idx).date()
    except (ValueError, TypeError):
        return None

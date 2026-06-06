"""Indicator compute + persist helper used by daily_ingestion.

Builds the :class:`IndicatorContext` once per daily run (loading
SPX + macro frames from the DB) then computes per-ticker indicators
and UPSERTs the resulting :class:`DailySignal` rows.

Keeps all "which data does an indicator need" plumbing out of the
daily_ingestion orchestrator proper, so the latter stays focused on
fetch+persist of raw data.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import structlog

from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.daily_signal_repository import (
    DailySignalRepository,
    DailySignalRow,
    result_to_row,
)
from app.db.repositories.macro_repository import MacroRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.indicators.base import INDICATOR_VERSION, IndicatorResult
from app.indicators.context import IndicatorContext
from app.indicators.orchestrator import compute_all, compute_market_regime

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.indicators")

_SPX_SYMBOL = "SPY"
# Macro series consumed by indicator modules.
_MACRO_SERIES: tuple[str, ...] = (
    "VIXCLS",
    "VXVCLS",
    "DGS10",
    "DGS2",
    "DTWEXBGS",
    "FEDFUNDS",
)


def build_context(
    *,
    db: Session,
    today: date,
) -> IndicatorContext:
    """Construct :class:`IndicatorContext` from persisted price + macro data.

    We load a 2-year SPX window — indicators only look at the tail, so
    this is bounded work regardless of total history length.
    """
    prices = DailyPriceRepository(db)
    macro = MacroRepository(db)

    spx_frame = _load_price_frame(prices, _SPX_SYMBOL, today)
    macro_frames: dict[str, pd.DataFrame] = {}
    for series_id in _MACRO_SERIES:
        frame = _load_macro_frame(macro, series_id, as_of=today)
        if frame is not None:
            macro_frames[series_id] = frame
    watchlist_breadth = _build_watchlist_breadth(db, prices, today)
    # Defensive deep copies so a misbehaving indicator that does an
    # in-place pandas operation (e.g. inplace=True, .iloc[...] = ...)
    # can't corrupt the shared context for later indicators in the
    # batch. frozen=True on the dataclass protects field rebinding but
    # NOT the mutability of the DataFrame objects it holds.
    return IndicatorContext(
        today=today,
        indicator_version=INDICATOR_VERSION,
        spx_frame=spx_frame.copy(deep=True) if spx_frame is not None else None,
        macro_frames={k: v.copy(deep=True) for k, v in macro_frames.items()},
        watchlist_breadth=watchlist_breadth.copy(deep=True)
        if watchlist_breadth is not None
        else None,
    )


def _build_watchlist_breadth(
    db: Session,
    prices: DailyPriceRepository,
    today: date,
) -> pd.DataFrame | None:
    """Aggregate the watchlist's daily advances / declines into an AD Line.

    Sums per-symbol close > prior_close into ``advances`` and close <
    prior_close into ``declines`` for each trading day in the past 2
    years. Cumulative sum of (advances - declines) gives the watchlist
    AD Line — same shape as NYSE breadth, scoped to the operator's
    actually-tracked universe.

    Returns ``None`` when the watchlist is empty (e.g. fresh install
    before any symbols are added) — the consuming indicator emits
    ``data_sufficient=False`` in that case.
    """
    symbols = list(WatchlistRepository(db).distinct_symbols_across_users())
    if not symbols:
        return None

    start = (pd.Timestamp(today) - pd.DateOffset(years=2)).date()
    direction_series: list[pd.Series] = []
    for sym in symbols:
        rows = prices.get_range(sym, start=start, end=today)
        if len(rows) < 2:
            continue
        s = pd.Series(
            [float(r.close) for r in rows],
            index=pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows]),
            dtype="float64",
        ).sort_index()
        direction_series.append(s.diff().rename(sym))

    if not direction_series:
        return None

    combined = pd.concat(direction_series, axis=1)
    advances = (combined > 0).sum(axis=1).rename("advances")
    declines = (combined < 0).sum(axis=1).rename("declines")
    net = (advances - declines).rename("net")
    ad_line = net.cumsum().rename("ad_line")
    return pd.concat([advances, declines, net, ad_line], axis=1)


def compute_and_persist(
    symbol: str,
    trade_date: date,
    *,
    db: Session,
    context: IndicatorContext,
) -> dict[str, IndicatorResult]:
    """Compute all per-ticker indicators and UPSERT their results.

    Returns the in-memory result dict so callers can log / inspect
    without re-reading from DB.
    """
    prices = DailyPriceRepository(db)
    signals = DailySignalRepository(db)

    price_frame = _load_price_frame(prices, symbol, trade_date)
    if price_frame is None:
        logger.info("indicator_compute_skipped_no_prices")
        return {}

    results = compute_all(symbol, price_frame, context)
    rows: list[DailySignalRow] = [
        result_to_row(symbol, trade_date, result) for result in results.values()
    ]
    signals.upsert_many(rows)
    return results


def compute_and_persist_market_regime(
    trade_date: date,
    *,
    db: Session,
    context: IndicatorContext,
) -> dict[str, IndicatorResult]:
    """Compute + UPSERT the 4 market-regime indicators against SPX."""
    signals = DailySignalRepository(db)
    results = compute_market_regime(context)
    rows = [result_to_row(_SPX_SYMBOL, trade_date, result) for result in results.values()]
    signals.upsert_many(rows)
    return results


def _load_price_frame(
    prices: DailyPriceRepository,
    symbol: str,
    today: date,
) -> pd.DataFrame | None:
    """Load a DB-stored OHLCV series into the DataFrame shape indicators expect.

    Returns ``None`` when no rows exist — callers decide whether
    that's a skip condition or an error.
    """
    # pd.Timestamp handles leap-year edge cases (``date.replace`` blows
    # up on Feb 29 → Feb 29 two years prior when prior is not leap).
    start = (pd.Timestamp(today) - pd.DateOffset(years=2)).date()
    rows = prices.get_range(symbol, start=start, end=today)
    if not rows:
        return None
    records = [
        {
            "date": r.date,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume),
        }
        for r in rows
    ]
    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def _load_macro_frame(
    macro: MacroRepository,
    series_id: str,
    *,
    as_of: date,
) -> pd.DataFrame | None:
    """Load a macro series as a value-indexed DataFrame.

    ``as_of`` caps the series at the session_day being computed so
    backfill can't leak future FRED data into historical indicator
    results (a pure lookahead bias).
    """
    rows = macro.get_all_for_series(series_id, as_of=as_of)
    if not rows:
        return None
    records = [{"date": r.date, "value": float(r.value)} for r in rows]
    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()

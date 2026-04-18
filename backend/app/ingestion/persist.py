"""DataFrame → DailyPrice row conversion.

Shared between :func:`backfill.backfill_ticker` and
:func:`daily_ingestion.run_daily_update` (rule 7: DRY). Does nothing
network-related — pure function over an already-fetched frame.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pandas as pd

from app.db.repositories.daily_price_repository import DailyPriceRow

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def iter_daily_price_rows(symbol: str, frame: pd.DataFrame) -> Iterator[DailyPriceRow]:
    """Yield UPSERT-ready rows from a normalized OHLCV frame.

    Rows with NaN in any required column are skipped — yfinance
    sometimes emits partial rows for early listing dates.
    """
    if frame.empty:
        return
    missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        return
    upper = symbol.upper()
    for idx, row in frame.iterrows():
        trade_date = _index_to_date(idx)
        if trade_date is None:
            continue
        values = [row["open"], row["high"], row["low"], row["close"]]
        if any(pd.isna(v) for v in values) or pd.isna(row["volume"]):
            continue
        try:
            open_ = Decimal(str(row["open"]))
            high = Decimal(str(row["high"]))
            low = Decimal(str(row["low"]))
            close = Decimal(str(row["close"]))
            vol = int(row["volume"])
        except (ValueError, TypeError, ArithmeticError):
            continue
        yield DailyPriceRow(
            symbol=upper,
            date=trade_date,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=vol,
        )


def _index_to_date(idx: object) -> date | None:
    if isinstance(idx, pd.Timestamp):
        return idx.date()
    if isinstance(idx, date):
        return idx
    try:
        return pd.Timestamp(idx).date()
    except (ValueError, TypeError):
        return None

"""DailyPrice UPSERT + range reads (A2).

UPSERT uses SQLite's ``INSERT ... ON CONFLICT DO UPDATE`` (NOT
``INSERT OR REPLACE`` which cascades foreign keys). The UNIQUE
constraint on ``(symbol, date)`` makes repeated ingestion of the same
day idempotent (rule 12).

Bulk path batches all rows into a single SQL statement — N individual
``add()`` calls would be O(N) round-trips (rule 10: no N+1).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import DailyPrice
from app.ingestion.market_calendar import get_trading_days, last_trading_day_et, today_et


class DailyPriceRow(TypedDict):
    """Raw dict shape the ingestion layer passes to :meth:`upsert_many`."""

    symbol: str
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class DailyPriceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[DailyPriceRow]) -> int:
        """UPSERT a batch. Returns count of rows attempted.

        SQLite doesn't report affected rows well through the ORM; we
        return the input size so callers can log throughput.
        """
        materialized: list[DailyPriceRow] = list(rows)
        if not materialized:
            return 0
        stmt = sqlite_insert(DailyPrice).values(materialized)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        return len(materialized)

    def get_range(self, symbol: str, *, start: date, end: date) -> Sequence[DailyPrice]:
        stmt = (
            select(DailyPrice)
            .where(
                DailyPrice.symbol == symbol.upper(),
                DailyPrice.date >= start,
                DailyPrice.date <= end,
            )
            .order_by(DailyPrice.date.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def get_latest(self, symbol: str) -> DailyPrice | None:
        stmt = (
            select(DailyPrice)
            .where(DailyPrice.symbol == symbol.upper())
            .order_by(DailyPrice.date.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def count_for_symbol(self, symbol: str) -> int:
        stmt = select(DailyPrice.id).where(DailyPrice.symbol == symbol.upper())
        return len(self._session.execute(stmt).scalars().all())

    def find_missing_dates(self, symbol: str, lookback_days: int = 60) -> list[date]:
        """Trading days within the lookback window with no DailyPrice row.

        ``lookback_days`` is expressed in NYSE **trading** days — the
        caller never has to reason about weekends or holidays.
        Computes the expected session set from the market calendar,
        diffs against rows already present for ``symbol``, returns the
        sorted list of missing session dates. Bounded window prevents a
        corrupted DB from triggering an unbounded refetch (invariant).
        """
        if lookback_days <= 0:
            return []
        end_date = last_trading_day_et(reference=today_et())
        # 2x the trading-day count (plus a small floor) gives a safe
        # calendar-day window — weekends + holidays eat at most ~30% of
        # calendar days, so 2x is a generous buffer before we slice.
        calendar_span = max(lookback_days * 2, lookback_days + 14)
        start_date = end_date - timedelta(days=calendar_span)
        expected = get_trading_days(start_date, end_date)
        if not expected:
            return []
        # Take only the last ``lookback_days`` sessions — the calendar
        # span above is generous on purpose so we trim here.
        expected = expected[-lookback_days:]
        window_start = expected[0]
        window_end = expected[-1]

        upper = symbol.upper()
        stmt = select(DailyPrice.date).where(
            DailyPrice.symbol == upper,
            DailyPrice.date >= window_start,
            DailyPrice.date <= window_end,
        )
        existing: set[date] = set(self._session.execute(stmt).scalars().all())
        return [d for d in expected if d not in existing]

    def find_gaps_for_symbols(
        self, symbols: list[str], lookback_days: int = 60
    ) -> dict[str, list[date]]:
        """Batch gap detection across many symbols in one round-trip.

        Returns a dict with an entry for every input symbol (empty list
        when that symbol has no gaps). Uses a single ``IN (...)`` query
        to avoid N+1 (rule 10) — the parameterized SQLAlchemy ``in_()``
        operator handles escaping.
        """
        if not symbols or lookback_days <= 0:
            return {s.upper(): [] for s in symbols}

        end_date = last_trading_day_et(reference=today_et())
        calendar_span = max(lookback_days * 2, lookback_days + 14)
        start_date = end_date - timedelta(days=calendar_span)
        expected = get_trading_days(start_date, end_date)
        if not expected:
            return {s.upper(): [] for s in symbols}
        expected = expected[-lookback_days:]
        expected_set = set(expected)
        window_start = expected[0]
        window_end = expected[-1]

        uppers = sorted({s.upper() for s in symbols if s.strip()})
        if not uppers:
            return {}

        stmt = select(DailyPrice.symbol, DailyPrice.date).where(
            DailyPrice.symbol.in_(uppers),
            DailyPrice.date >= window_start,
            DailyPrice.date <= window_end,
        )
        present: dict[str, set[date]] = {sym: set() for sym in uppers}
        for sym, d in self._session.execute(stmt).all():
            if sym in present:
                present[sym].add(d)

        gaps: dict[str, list[date]] = {}
        for sym in uppers:
            missing = sorted(expected_set - present[sym])
            gaps[sym] = missing
        return gaps

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
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import DailyPrice


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

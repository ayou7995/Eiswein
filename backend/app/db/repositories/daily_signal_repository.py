"""DailySignal UPSERT + per-ticker reads (Phase 2, A2).

Same UPSERT pattern as DailyPrice / MacroIndicator: SQLite's
``INSERT ... ON CONFLICT DO UPDATE`` keyed on the UNIQUE
``(symbol, date, indicator_name)`` constraint. Re-running
``daily_update`` the same day replaces the previous day's row
in-place, which is what we want because the numeric inputs will
typically be identical (idempotent, rule 12).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import DailySignal
from app.indicators.base import IndicatorResult


class DailySignalRow(TypedDict):
    symbol: str
    date: date
    indicator_name: str
    signal: str
    value: Decimal | None
    data_sufficient: bool
    short_label: str
    detail: dict[str, Any]
    indicator_version: str
    computed_at: datetime


def result_to_row(
    symbol: str,
    trade_date: date,
    result: IndicatorResult,
) -> DailySignalRow:
    """Convert an in-memory :class:`IndicatorResult` to an UPSERT row.

    ``value`` is stored as :class:`Decimal` so numeric comparisons in
    SQL stay exact; ``Decimal(str(float))`` preserves the repr
    precision yfinance serves rather than the binary float value.
    """
    value = None if result.value is None else Decimal(str(result.value))
    return DailySignalRow(
        symbol=symbol.upper(),
        date=trade_date,
        indicator_name=result.name,
        signal=result.signal,
        value=value,
        data_sufficient=result.data_sufficient,
        short_label=result.short_label,
        detail=dict(result.detail),
        indicator_version=result.indicator_version,
        computed_at=result.computed_at,
    )


class DailySignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[DailySignalRow]) -> int:
        materialized: list[DailySignalRow] = list(rows)
        if not materialized:
            return 0
        stmt = sqlite_insert(DailySignal).values(materialized)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date", "indicator_name"],
            set_={
                "signal": stmt.excluded.signal,
                "value": stmt.excluded.value,
                "data_sufficient": stmt.excluded.data_sufficient,
                "short_label": stmt.excluded.short_label,
                "detail": stmt.excluded.detail,
                "indicator_version": stmt.excluded.indicator_version,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        return len(materialized)

    def get_latest_for_symbol(self, symbol: str) -> Sequence[DailySignal]:
        """Return the most recent set of signals for this symbol.

        "Most recent" == all rows whose ``date`` equals the latest
        stored date for the symbol. Typically that's one batch of
        ~8 rows (one per indicator) produced by the last daily_update.
        """
        latest_date_stmt = (
            select(DailySignal.date)
            .where(DailySignal.symbol == symbol.upper())
            .order_by(DailySignal.date.desc())
            .limit(1)
        )
        latest_date = self._session.execute(latest_date_stmt).scalar_one_or_none()
        if latest_date is None:
            return []
        rows_stmt = select(DailySignal).where(
            DailySignal.symbol == symbol.upper(),
            DailySignal.date == latest_date,
        )
        return self._session.execute(rows_stmt).scalars().all()

    def get_range(
        self,
        symbol: str,
        *,
        start_date: date,
        end_date: date,
        indicator_name: str | None = None,
    ) -> Sequence[DailySignal]:
        filters = [
            DailySignal.symbol == symbol.upper(),
            DailySignal.date >= start_date,
            DailySignal.date <= end_date,
        ]
        if indicator_name is not None:
            filters.append(DailySignal.indicator_name == indicator_name)
        stmt = (
            select(DailySignal)
            .where(*filters)
            .order_by(DailySignal.date.asc(), DailySignal.indicator_name.asc())
        )
        return self._session.execute(stmt).scalars().all()

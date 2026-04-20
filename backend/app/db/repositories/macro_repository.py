"""MacroIndicator UPSERT + latest-value reads (A2).

Same idempotent UPSERT pattern as DailyPrice — FRED sometimes
back-revises values, so ``on_conflict_do_update`` is required to keep
us current.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import MacroIndicator


class MacroRow(TypedDict):
    series_id: str
    date: date
    value: Decimal


class MacroRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[MacroRow]) -> int:
        materialized: list[MacroRow] = list(rows)
        if not materialized:
            return 0
        # SQLite's SQLITE_MAX_VARIABLE_NUMBER caps variables per statement
        # (32766 on modern builds). FRED series go back decades, so a
        # single INSERT with ~11k rows × 3 cols overshoots. Batch to stay
        # well inside the limit across SQLite versions.
        batch_size = 500
        for start in range(0, len(materialized), batch_size):
            chunk = materialized[start : start + batch_size]
            stmt = sqlite_insert(MacroIndicator).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["series_id", "date"],
                set_={"value": stmt.excluded.value},
            )
            self._session.execute(stmt)
        self._session.flush()
        return len(materialized)

    def get_latest(self, series_id: str) -> MacroIndicator | None:
        stmt = (
            select(MacroIndicator)
            .where(MacroIndicator.series_id == series_id.upper())
            .order_by(MacroIndicator.date.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_all_for_series(self, series_id: str) -> list[MacroIndicator]:
        """All stored rows for the series, oldest-first.

        Used by the Phase 2 indicator context builder: macro windows
        are bounded (20-day SMA, 30-day delta) but we still read the
        full series because FRED sometimes back-revises historical
        values and we want the latest snapshot in the in-memory frame.
        """
        stmt = (
            select(MacroIndicator)
            .where(MacroIndicator.series_id == series_id.upper())
            .order_by(MacroIndicator.date.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def count_for_series(self, series_id: str) -> int:
        stmt = select(MacroIndicator.id).where(MacroIndicator.series_id == series_id.upper())
        return len(self._session.execute(stmt).scalars().all())

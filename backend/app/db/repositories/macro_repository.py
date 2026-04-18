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
        stmt = sqlite_insert(MacroIndicator).values(materialized)
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

    def count_for_series(self, series_id: str) -> int:
        stmt = select(MacroIndicator.id).where(MacroIndicator.series_id == series_id.upper())
        return len(self._session.execute(stmt).scalars().all())

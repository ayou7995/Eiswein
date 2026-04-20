"""MarketSnapshot UPSERT + latest-read (Phase 3).

Single global row per trading day — keyed on UNIQUE(date). Mirrors
the DailySignal UPSERT pattern.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import MarketSnapshot
from app.signals.types import MarketPosture


class MarketSnapshotRow(TypedDict):
    date: date
    posture: str
    regime_green_count: int
    regime_red_count: int
    regime_yellow_count: int
    indicator_version: str
    computed_at: datetime


def build_market_snapshot_row(
    *,
    trade_date: date,
    posture: MarketPosture,
    regime_green_count: int,
    regime_red_count: int,
    regime_yellow_count: int,
    indicator_version: str,
    computed_at: datetime,
) -> MarketSnapshotRow:
    return MarketSnapshotRow(
        date=trade_date,
        posture=posture.value,
        regime_green_count=regime_green_count,
        regime_red_count=regime_red_count,
        regime_yellow_count=regime_yellow_count,
        indicator_version=indicator_version,
        computed_at=computed_at,
    )


class MarketSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, row: MarketSnapshotRow) -> None:
        stmt = sqlite_insert(MarketSnapshot).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={
                "posture": stmt.excluded.posture,
                "regime_green_count": stmt.excluded.regime_green_count,
                "regime_red_count": stmt.excluded.regime_red_count,
                "regime_yellow_count": stmt.excluded.regime_yellow_count,
                "indicator_version": stmt.excluded.indicator_version,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        self._session.execute(stmt)
        self._session.flush()

    def get_latest(self) -> MarketSnapshot | None:
        stmt = select(MarketSnapshot).order_by(MarketSnapshot.date.desc()).limit(1)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_for_date(self, trade_date: date) -> MarketSnapshot | None:
        stmt = select(MarketSnapshot).where(MarketSnapshot.date == trade_date)
        return self._session.execute(stmt).scalar_one_or_none()

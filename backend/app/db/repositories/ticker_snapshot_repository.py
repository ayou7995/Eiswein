"""TickerSnapshot UPSERT + latest-read (Phase 3).

Mirrors the DailySignal repository pattern — SQLite
``INSERT ... ON CONFLICT DO UPDATE`` keyed on UNIQUE(symbol, date).
Repeated ingestion of the same day is idempotent (rule 12).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import TickerSnapshot
from app.signals.types import ComposedSignal


class TickerSnapshotRow(TypedDict):
    symbol: str
    date: date
    action: str
    direction_green_count: int
    direction_red_count: int
    timing_modifier: str
    show_timing_modifier: bool
    entry_aggressive: Decimal | None
    entry_ideal: Decimal | None
    entry_conservative: Decimal | None
    stop_loss: Decimal | None
    market_posture_at_compute: str
    indicator_version: str
    computed_at: datetime


def composed_to_row(signal: ComposedSignal) -> TickerSnapshotRow:
    """Project a :class:`ComposedSignal` to the UPSERT row TypedDict.

    Enum values are serialized via ``.value`` so the column stores the
    short stable string (``"strong_buy"`` etc.) rather than the enum
    repr.
    """
    return TickerSnapshotRow(
        symbol=signal.symbol.upper(),
        date=signal.date,
        action=signal.action.value,
        direction_green_count=signal.direction_green_count,
        direction_red_count=signal.direction_red_count,
        timing_modifier=signal.timing_modifier.value,
        show_timing_modifier=signal.show_timing_modifier,
        entry_aggressive=signal.entry_tiers.aggressive,
        entry_ideal=signal.entry_tiers.ideal,
        entry_conservative=signal.entry_tiers.conservative,
        stop_loss=signal.stop_loss,
        market_posture_at_compute=signal.market_posture_at_compute.value,
        indicator_version=signal.indicator_version,
        computed_at=signal.computed_at,
    )


class TickerSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[TickerSnapshotRow]) -> int:
        materialized: list[TickerSnapshotRow] = list(rows)
        if not materialized:
            return 0
        stmt = sqlite_insert(TickerSnapshot).values(materialized)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "action": stmt.excluded.action,
                "direction_green_count": stmt.excluded.direction_green_count,
                "direction_red_count": stmt.excluded.direction_red_count,
                "timing_modifier": stmt.excluded.timing_modifier,
                "show_timing_modifier": stmt.excluded.show_timing_modifier,
                "entry_aggressive": stmt.excluded.entry_aggressive,
                "entry_ideal": stmt.excluded.entry_ideal,
                "entry_conservative": stmt.excluded.entry_conservative,
                "stop_loss": stmt.excluded.stop_loss,
                "market_posture_at_compute": stmt.excluded.market_posture_at_compute,
                "indicator_version": stmt.excluded.indicator_version,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        return len(materialized)

    def get_latest_for_symbol(self, symbol: str) -> TickerSnapshot | None:
        stmt = (
            select(TickerSnapshot)
            .where(TickerSnapshot.symbol == symbol.upper())
            .order_by(TickerSnapshot.date.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_for_symbol(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[TickerSnapshot]:
        """All stored snapshots for ``symbol`` ordered by date asc.

        Used by the back-test accuracy endpoint — we need every past
        action to compare against forward returns.
        """
        filters = [TickerSnapshot.symbol == symbol.upper()]
        if start_date is not None:
            filters.append(TickerSnapshot.date >= start_date)
        if end_date is not None:
            filters.append(TickerSnapshot.date <= end_date)
        stmt = select(TickerSnapshot).where(*filters).order_by(TickerSnapshot.date.asc())
        return self._session.execute(stmt).scalars().all()

    def list_for_date(self, session_date: date) -> Sequence[TickerSnapshot]:
        """All snapshots written for a specific trading day.

        Used by the Phase 6 daily-summary email to surface any
        ``strong_buy`` / ``buy`` / ``reduce`` / ``exit`` rows the
        freshly-completed ``run_daily_update`` produced.
        """
        stmt = (
            select(TickerSnapshot)
            .where(TickerSnapshot.date == session_date)
            .order_by(TickerSnapshot.symbol.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def get_on_or_before(self, *, symbol: str, on_or_before: date) -> TickerSnapshot | None:
        """Best-effort: the most recent snapshot at or before ``on_or_before``.

        Trades executed on non-trading-days (or before that day's
        snapshot was computed) still need an action to match against —
        the most recent stored snapshot is the fairest comparison.
        """
        stmt = (
            select(TickerSnapshot)
            .where(
                TickerSnapshot.symbol == symbol.upper(),
                TickerSnapshot.date <= on_or_before,
            )
            .order_by(TickerSnapshot.date.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

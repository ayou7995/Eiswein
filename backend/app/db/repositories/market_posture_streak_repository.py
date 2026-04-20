"""MarketPostureStreak repository (D3).

Tracks consecutive days of the same market posture for the dashboard
"進攻 3 天 ✨" badge. Streak advances when today's posture matches the
prior row; resets to 1 otherwise.

Separate from MarketSnapshot so dashboard reads that need only the
current streak don't have to scan N historical snapshots.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import MarketPostureStreak
from app.signals.types import MarketPosture


class MarketPostureStreakRow(TypedDict):
    as_of_date: date
    current_posture: str
    streak_days: int
    streak_started_on: date
    computed_at: datetime


class MarketPostureStreakRepository:
    """UPSERT streak rows with continuity-aware logic.

    ``record_posture`` is the main entry point: it reads the most
    recent streak row strictly before ``as_of_date`` and advances or
    resets accordingly.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_latest(self) -> MarketPostureStreak | None:
        stmt = select(MarketPostureStreak).order_by(MarketPostureStreak.as_of_date.desc()).limit(1)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_for_date(self, as_of_date: date) -> MarketPostureStreak | None:
        stmt = select(MarketPostureStreak).where(MarketPostureStreak.as_of_date == as_of_date)
        return self._session.execute(stmt).scalar_one_or_none()

    def _get_previous(self, *, before: date) -> MarketPostureStreak | None:
        """Return the most recent streak row strictly before ``before``.

        Used to decide whether today advances or resets the streak.
        Idempotent re-runs of the daily job for the same date must NOT
        stack: the prior row must be strictly earlier (< not ≤).
        """
        stmt = (
            select(MarketPostureStreak)
            .where(MarketPostureStreak.as_of_date < before)
            .order_by(MarketPostureStreak.as_of_date.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def record_posture(
        self,
        *,
        as_of_date: date,
        posture: MarketPosture,
        computed_at: datetime,
    ) -> MarketPostureStreakRow:
        """Advance or reset the streak and UPSERT today's row.

        Returns the row that was written so callers can log / inspect
        the final state without a second DB round-trip.
        """
        prior = self._get_previous(before=as_of_date)
        if prior is not None and prior.current_posture == posture.value:
            streak_days = prior.streak_days + 1
            streak_started_on = prior.streak_started_on
        else:
            streak_days = 1
            streak_started_on = as_of_date

        row = MarketPostureStreakRow(
            as_of_date=as_of_date,
            current_posture=posture.value,
            streak_days=streak_days,
            streak_started_on=streak_started_on,
            computed_at=computed_at,
        )
        stmt = sqlite_insert(MarketPostureStreak).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["as_of_date"],
            set_={
                "current_posture": stmt.excluded.current_posture,
                "streak_days": stmt.excluded.streak_days,
                "streak_started_on": stmt.excluded.streak_started_on,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        return row

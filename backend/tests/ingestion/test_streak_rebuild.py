"""Rebuild streak table from market_snapshot rows — idempotency + seed."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import MarketPostureStreak, MarketSnapshot
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.ingestion.streak_rebuild import rebuild_streak_table
from app.signals.types import MarketPosture

_ = Decimal  # silence unused import in case we expand later


def _insert_snapshot(
    session: Session,
    *,
    d: date,
    posture: MarketPosture,
) -> None:
    session.add(
        MarketSnapshot(
            date=d,
            posture=posture.value,
            regime_green_count=0,
            regime_red_count=0,
            regime_yellow_count=0,
            indicator_version="0.0.0",
            computed_at=datetime.now(UTC),
        )
    )


def test_rebuild_from_scratch_writes_streaks_for_all_days(db_session: Session) -> None:
    _insert_snapshot(db_session, d=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 4), posture=MarketPosture.DEFENSIVE)
    db_session.flush()

    written = rebuild_streak_table(db=db_session)
    db_session.commit()

    assert written == 3
    repo = MarketPostureStreakRepository(db_session)
    day2 = repo.get_for_date(date(2024, 1, 2))
    day3 = repo.get_for_date(date(2024, 1, 3))
    day4 = repo.get_for_date(date(2024, 1, 4))
    assert day2 is not None and day2.streak_days == 1
    assert day3 is not None and day3.streak_days == 2
    assert day3.streak_started_on == date(2024, 1, 2)
    assert day4 is not None and day4.streak_days == 1
    assert day4.current_posture == MarketPosture.DEFENSIVE.value
    assert day4.streak_started_on == date(2024, 1, 4)


def test_rebuild_is_idempotent(db_session: Session) -> None:
    _insert_snapshot(db_session, d=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    db_session.flush()

    rebuild_streak_table(db=db_session)
    rebuild_streak_table(db=db_session)
    db_session.commit()

    rows = db_session.query(MarketPostureStreak).all()
    assert len(rows) == 2
    # Ordered by date.
    ordered = sorted(rows, key=lambda r: r.as_of_date)
    assert ordered[0].streak_days == 1
    assert ordered[1].streak_days == 2


def test_rebuild_from_date_seeds_from_prior_row(db_session: Session) -> None:
    # Seed a "prior" streak row that an incremental rebuild should pick
    # up — simulates a backfill over only Jan 4-5 that must know the
    # Jan 2-3 streak still runs.
    _insert_snapshot(db_session, d=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 4), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 5), posture=MarketPosture.OFFENSIVE)
    db_session.flush()

    # Full rebuild first, then re-run starting from Jan 4 — should
    # produce the same final state.
    rebuild_streak_table(db=db_session)
    rebuild_streak_table(db=db_session, from_date=date(2024, 1, 4))
    db_session.commit()

    repo = MarketPostureStreakRepository(db_session)
    day5 = repo.get_for_date(date(2024, 1, 5))
    assert day5 is not None
    assert day5.streak_days == 4
    assert day5.streak_started_on == date(2024, 1, 2)


def test_rebuild_from_date_without_seed_starts_fresh(db_session: Session) -> None:
    # No prior streak row exists for Jan 3 → Jan 4 rebuild must start
    # a fresh streak at the from_date.
    _insert_snapshot(db_session, d=date(2024, 1, 4), posture=MarketPosture.OFFENSIVE)
    _insert_snapshot(db_session, d=date(2024, 1, 5), posture=MarketPosture.OFFENSIVE)
    db_session.flush()

    rebuild_streak_table(db=db_session, from_date=date(2024, 1, 4))
    db_session.commit()

    repo = MarketPostureStreakRepository(db_session)
    day4 = repo.get_for_date(date(2024, 1, 4))
    day5 = repo.get_for_date(date(2024, 1, 5))
    assert day4 is not None and day4.streak_days == 1
    assert day5 is not None and day5.streak_days == 2
    assert day5.streak_started_on == date(2024, 1, 4)


def test_rebuild_empty_snapshot_table_returns_zero(db_session: Session) -> None:
    written = rebuild_streak_table(db=db_session)
    db_session.commit()
    assert written == 0

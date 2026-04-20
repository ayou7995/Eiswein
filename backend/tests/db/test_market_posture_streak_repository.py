"""MarketPostureStreak increment / reset tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.signals.types import MarketPosture


def _record(
    repo: MarketPostureStreakRepository,
    *,
    as_of: date,
    posture: MarketPosture,
) -> None:
    repo.record_posture(
        as_of_date=as_of,
        posture=posture,
        computed_at=datetime.now(UTC),
    )


def test_first_posture_starts_streak_at_1(db_session: Session) -> None:
    repo = MarketPostureStreakRepository(db_session)
    _record(repo, as_of=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    db_session.commit()

    row = repo.get_latest()
    assert row is not None
    assert row.current_posture == MarketPosture.OFFENSIVE.value
    assert row.streak_days == 1
    assert row.streak_started_on == date(2024, 1, 2)


def test_same_posture_advances_streak(db_session: Session) -> None:
    repo = MarketPostureStreakRepository(db_session)
    _record(repo, as_of=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _record(repo, as_of=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    _record(repo, as_of=date(2024, 1, 4), posture=MarketPosture.OFFENSIVE)
    db_session.commit()

    latest = repo.get_latest()
    assert latest is not None
    assert latest.streak_days == 3
    assert latest.streak_started_on == date(2024, 1, 2)


def test_different_posture_resets_streak(db_session: Session) -> None:
    repo = MarketPostureStreakRepository(db_session)
    _record(repo, as_of=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _record(repo, as_of=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    _record(repo, as_of=date(2024, 1, 4), posture=MarketPosture.DEFENSIVE)
    db_session.commit()

    latest = repo.get_latest()
    assert latest is not None
    assert latest.current_posture == MarketPosture.DEFENSIVE.value
    assert latest.streak_days == 1
    assert latest.streak_started_on == date(2024, 1, 4)


def test_re_running_same_date_is_idempotent(db_session: Session) -> None:
    """Idempotency rule 12: re-running daily_update for the same date must
    not stack the streak (the previous-row lookup is strictly <, not ≤)."""
    repo = MarketPostureStreakRepository(db_session)
    _record(repo, as_of=date(2024, 1, 2), posture=MarketPosture.OFFENSIVE)
    _record(repo, as_of=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    # Simulate second run of daily_update for 2024-01-03.
    _record(repo, as_of=date(2024, 1, 3), posture=MarketPosture.OFFENSIVE)
    db_session.commit()

    latest = repo.get_latest()
    assert latest is not None
    assert latest.streak_days == 2  # Still 2, not 3.
    assert latest.streak_started_on == date(2024, 1, 2)


def test_record_returns_final_row(db_session: Session) -> None:
    repo = MarketPostureStreakRepository(db_session)
    row = repo.record_posture(
        as_of_date=date(2024, 1, 2),
        posture=MarketPosture.OFFENSIVE,
        computed_at=datetime.now(UTC),
    )
    db_session.commit()
    assert row["streak_days"] == 1
    assert row["current_posture"] == MarketPosture.OFFENSIVE.value
    assert row["streak_started_on"] == date(2024, 1, 2)

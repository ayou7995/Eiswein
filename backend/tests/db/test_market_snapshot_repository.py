"""MarketSnapshot UPSERT + UNIQUE(date) enforcement tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import MarketSnapshot
from app.db.repositories.market_snapshot_repository import (
    MarketSnapshotRepository,
    build_market_snapshot_row,
)
from app.signals.types import MarketPosture


def test_upsert_new_row(db_session: Session) -> None:
    repo = MarketSnapshotRepository(db_session)
    row = build_market_snapshot_row(
        trade_date=date(2024, 12, 31),
        posture=MarketPosture.OFFENSIVE,
        regime_green_count=3,
        regime_red_count=0,
        regime_yellow_count=1,
        indicator_version="1.0.0",
        computed_at=datetime.now(UTC),
    )
    repo.upsert(row)
    db_session.commit()

    latest = repo.get_latest()
    assert latest is not None
    assert latest.posture == MarketPosture.OFFENSIVE.value
    assert latest.regime_green_count == 3


def test_upsert_replaces_on_date_conflict(db_session: Session) -> None:
    repo = MarketSnapshotRepository(db_session)
    today = date(2024, 12, 31)
    repo.upsert(
        build_market_snapshot_row(
            trade_date=today,
            posture=MarketPosture.OFFENSIVE,
            regime_green_count=3,
            regime_red_count=0,
            regime_yellow_count=1,
            indicator_version="1.0.0",
            computed_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    repo.upsert(
        build_market_snapshot_row(
            trade_date=today,
            posture=MarketPosture.DEFENSIVE,
            regime_green_count=0,
            regime_red_count=3,
            regime_yellow_count=1,
            indicator_version="1.0.0",
            computed_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    # Only one row survives — UNIQUE(date) enforces it.
    stored = db_session.query(MarketSnapshot).filter_by(date=today).all()
    assert len(stored) == 1
    assert stored[0].posture == MarketPosture.DEFENSIVE.value


def test_get_for_date_returns_matching_row(db_session: Session) -> None:
    repo = MarketSnapshotRepository(db_session)
    target = date(2024, 12, 31)
    repo.upsert(
        build_market_snapshot_row(
            trade_date=target,
            posture=MarketPosture.NORMAL,
            regime_green_count=2,
            regime_red_count=0,
            regime_yellow_count=2,
            indicator_version="1.0.0",
            computed_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    row = repo.get_for_date(target)
    assert row is not None
    assert row.date == target
    assert repo.get_for_date(date(2025, 1, 1)) is None


def test_raw_insert_violates_unique_date(db_session: Session) -> None:
    """Direct INSERT of a second row on same date MUST fail (UNIQUE)."""
    repo = MarketSnapshotRepository(db_session)
    target = date(2024, 12, 31)
    repo.upsert(
        build_market_snapshot_row(
            trade_date=target,
            posture=MarketPosture.NORMAL,
            regime_green_count=2,
            regime_red_count=0,
            regime_yellow_count=2,
            indicator_version="1.0.0",
            computed_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    # A naive add() that bypasses ON CONFLICT DO UPDATE must fail.
    db_session.add(
        MarketSnapshot(
            date=target,
            posture=MarketPosture.OFFENSIVE.value,
            regime_green_count=3,
            regime_red_count=0,
            regime_yellow_count=1,
            indicator_version="1.0.0",
            computed_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

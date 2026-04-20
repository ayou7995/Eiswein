"""TickerSnapshot UPSERT + read tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.repositories.ticker_snapshot_repository import (
    TickerSnapshotRepository,
    composed_to_row,
)
from app.signals.compose import compose_signal
from app.signals.types import (
    ActionCategory,
    EntryTiers,
    MarketPosture,
    TimingModifier,
)


def _make_composed(
    *,
    symbol: str = "AAPL",
    trade_date: date | None = None,
    action: ActionCategory = ActionCategory.HOLD,
    timing: TimingModifier = TimingModifier.MIXED,
    stop_loss: Decimal | None = Decimal("95.0000"),
):
    return compose_signal(
        symbol=symbol,
        trade_date=trade_date or date(2024, 12, 31),
        action=action,
        direction_green_count=2,
        direction_red_count=0,
        timing_modifier=timing,
        market_posture=MarketPosture.NORMAL,
        entry_tiers=EntryTiers(
            aggressive=Decimal("100.0000"),
            ideal=Decimal("99.0000"),
            conservative=Decimal("90.0000"),
        ),
        stop_loss=stop_loss,
        computed_at=datetime.now(UTC),
    )


def test_upsert_and_read_latest(db_session: Session) -> None:
    repo = TickerSnapshotRepository(db_session)
    composed = _make_composed()
    count = repo.upsert_many([composed_to_row(composed)])
    assert count == 1
    db_session.commit()

    latest = repo.get_latest_for_symbol("AAPL")
    assert latest is not None
    assert latest.action == ActionCategory.HOLD.value
    assert latest.direction_green_count == 2
    assert latest.entry_aggressive == Decimal("100.0000")
    assert latest.stop_loss == Decimal("95.0000")


def test_upsert_replaces_on_conflict(db_session: Session) -> None:
    repo = TickerSnapshotRepository(db_session)
    repo.upsert_many([composed_to_row(_make_composed(action=ActionCategory.HOLD))])
    db_session.commit()
    # Same (symbol, date) with a different action → replaces.
    repo.upsert_many([composed_to_row(_make_composed(action=ActionCategory.STRONG_BUY))])
    db_session.commit()
    latest = repo.get_latest_for_symbol("AAPL")
    assert latest is not None
    assert latest.action == ActionCategory.STRONG_BUY.value


def test_get_latest_returns_most_recent_date(db_session: Session) -> None:
    repo = TickerSnapshotRepository(db_session)
    old = date(2024, 12, 30)
    new = date(2024, 12, 31)
    repo.upsert_many([composed_to_row(_make_composed(trade_date=old, action=ActionCategory.HOLD))])
    repo.upsert_many([composed_to_row(_make_composed(trade_date=new, action=ActionCategory.BUY))])
    db_session.commit()
    latest = repo.get_latest_for_symbol("AAPL")
    assert latest is not None
    assert latest.date == new
    assert latest.action == ActionCategory.BUY.value


def test_get_latest_unknown_symbol_is_none(db_session: Session) -> None:
    repo = TickerSnapshotRepository(db_session)
    assert repo.get_latest_for_symbol("NOPE") is None


def test_null_stop_loss_persisted(db_session: Session) -> None:
    repo = TickerSnapshotRepository(db_session)
    composed = _make_composed(stop_loss=None)
    repo.upsert_many([composed_to_row(composed)])
    db_session.commit()
    latest = repo.get_latest_for_symbol("AAPL")
    assert latest is not None
    assert latest.stop_loss is None

"""DailyPriceRepository — UPSERT idempotency + range queries."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DailyPrice
from app.db.repositories.daily_price_repository import (
    DailyPriceRepository,
    DailyPriceRow,
)


def _row(day: date, close: str) -> DailyPriceRow:
    return DailyPriceRow(
        symbol="SPY",
        date=day,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=1_000_000,
    )


def test_upsert_many_inserts_new_rows(db_session: Session) -> None:
    repo = DailyPriceRepository(db_session)
    upserted = repo.upsert_many([_row(date(2026, 4, 1), "100"), _row(date(2026, 4, 2), "101")])
    assert upserted == 2
    assert repo.count_for_symbol("SPY") == 2


def test_upsert_many_updates_existing_on_conflict(db_session: Session) -> None:
    repo = DailyPriceRepository(db_session)
    repo.upsert_many([_row(date(2026, 4, 1), "100")])
    repo.upsert_many([_row(date(2026, 4, 1), "150")])
    assert repo.count_for_symbol("SPY") == 1
    latest = repo.get_latest("SPY")
    assert latest is not None
    assert latest.close == Decimal("150.0000")


def test_get_range_filters_by_date(db_session: Session) -> None:
    repo = DailyPriceRepository(db_session)
    repo.upsert_many(
        [
            _row(date(2026, 4, 1), "100"),
            _row(date(2026, 4, 2), "101"),
            _row(date(2026, 4, 3), "102"),
        ]
    )
    rows = repo.get_range("SPY", start=date(2026, 4, 2), end=date(2026, 4, 3))
    assert [r.date for r in rows] == [date(2026, 4, 2), date(2026, 4, 3)]


def test_upsert_many_empty_is_noop(db_session: Session) -> None:
    repo = DailyPriceRepository(db_session)
    assert repo.upsert_many([]) == 0
    assert repo.count_for_symbol("SPY") == 0


def test_upsert_many_sets_updated_at_on_insert(db_session: Session) -> None:
    """Fresh INSERT through the UPSERT path stamps updated_at."""
    repo = DailyPriceRepository(db_session)
    repo.upsert_many([_row(date(2026, 4, 1), "100")])
    latest = repo.get_latest("SPY")
    assert latest is not None
    assert latest.updated_at is not None


def test_upsert_many_advances_updated_at_on_overwrite(db_session: Session) -> None:
    """Overwriting an existing (symbol, date) bumps updated_at — this
    is the primitive the freshness layer relies on to tell a partial
    intra-day write apart from a finalized post-close write.
    """
    repo = DailyPriceRepository(db_session)
    repo.upsert_many([_row(date(2026, 4, 1), "100")])
    first = repo.get_latest("SPY")
    assert first is not None
    first_stamp = first.updated_at

    # Sleep just long enough that the second write's UTC timestamp is
    # strictly greater. SQLite's DATETIME has microsecond resolution,
    # so a ~10ms gap is plenty in practice.
    time.sleep(0.05)

    repo.upsert_many([_row(date(2026, 4, 1), "150")])
    # Re-fetch from DB rather than reusing the stale ORM instance —
    # ON CONFLICT DO UPDATE happens server-side, not through the
    # session's unit of work, so the ORM cache can be stale.
    db_session.expire_all()
    second = repo.get_latest("SPY")
    assert second is not None
    assert second.close == Decimal("150.0000")
    assert second.updated_at > first_stamp


def test_upsert_many_updated_at_is_unique_per_row(db_session: Session) -> None:
    """A batched INSERT writes the same UTC stamp to all rows in the
    batch — the partial-bar detection is per-symbol, not per-row,
    so a shared timestamp inside one call is fine.
    """
    repo = DailyPriceRepository(db_session)
    repo.upsert_many(
        [_row(date(2026, 4, 1), "100"), _row(date(2026, 4, 2), "101")]
    )
    rows = (
        db_session.query(DailyPrice)
        .filter(DailyPrice.symbol == "SPY")
        .order_by(DailyPrice.date)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].updated_at == rows[1].updated_at

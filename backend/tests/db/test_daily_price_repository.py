"""DailyPriceRepository — UPSERT idempotency + range queries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

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
    upserted = repo.upsert_many(
        [_row(date(2026, 4, 1), "100"), _row(date(2026, 4, 2), "101")]
    )
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

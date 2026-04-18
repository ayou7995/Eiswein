"""MacroRepository — UPSERT idempotency + latest lookup."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.repositories.macro_repository import MacroRepository, MacroRow


def test_upsert_many_then_get_latest(db_session: Session) -> None:
    repo = MacroRepository(db_session)
    repo.upsert_many(
        [
            MacroRow(series_id="DGS10", date=date(2026, 4, 1), value=Decimal("4.35")),
            MacroRow(series_id="DGS10", date=date(2026, 4, 2), value=Decimal("4.40")),
        ]
    )
    latest = repo.get_latest("DGS10")
    assert latest is not None
    assert latest.date == date(2026, 4, 2)
    assert latest.value == Decimal("4.400000")


def test_upsert_updates_existing_conflict(db_session: Session) -> None:
    repo = MacroRepository(db_session)
    repo.upsert_many([MacroRow(series_id="FEDFUNDS", date=date(2026, 4, 1), value=Decimal("5.25"))])
    repo.upsert_many([MacroRow(series_id="FEDFUNDS", date=date(2026, 4, 1), value=Decimal("5.00"))])
    latest = repo.get_latest("FEDFUNDS")
    assert latest is not None
    assert latest.value == Decimal("5.000000")
    assert repo.count_for_series("FEDFUNDS") == 1

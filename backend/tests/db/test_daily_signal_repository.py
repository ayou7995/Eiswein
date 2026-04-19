"""DailySignalRepository UPSERT + read tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.db.repositories.daily_signal_repository import (
    DailySignalRepository,
    result_to_row,
)
from app.indicators.base import IndicatorResult, SignalTone


def _make_result(
    name: str = "rsi",
    *,
    value: float | None = 55.5,
    signal: str = SignalTone.YELLOW,
) -> IndicatorResult:
    return IndicatorResult(
        name=name,
        value=value,
        signal=signal,  # type: ignore[arg-type]
        data_sufficient=True,
        short_label=f"{name} 測試",
        detail={"foo": "bar"},
        computed_at=datetime.now(UTC),
    )


def test_upsert_and_read_latest(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    today = date(2024, 12, 31)
    rows = [
        result_to_row("AAPL", today, _make_result("rsi")),
        result_to_row("AAPL", today, _make_result("macd", value=1.2)),
    ]
    count = repo.upsert_many(rows)
    assert count == 2
    db_session.commit()

    latest = repo.get_latest_for_symbol("AAPL")
    names = {r.indicator_name for r in latest}
    assert names == {"rsi", "macd"}


def test_upsert_replaces_on_conflict(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    today = date(2024, 12, 31)

    r1 = result_to_row("AAPL", today, _make_result("rsi", value=50.0))
    repo.upsert_many([r1])
    db_session.commit()

    r2 = result_to_row("AAPL", today, _make_result("rsi", value=70.0))
    repo.upsert_many([r2])
    db_session.commit()

    latest = repo.get_latest_for_symbol("AAPL")
    assert len(latest) == 1
    assert float(latest[0].value) == 70.0


def test_get_latest_returns_most_recent_date(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    old = date(2024, 12, 30)
    new = date(2024, 12, 31)
    repo.upsert_many([result_to_row("AAPL", old, _make_result("rsi", value=50.0))])
    repo.upsert_many([result_to_row("AAPL", new, _make_result("rsi", value=60.0))])
    db_session.commit()

    latest = repo.get_latest_for_symbol("AAPL")
    assert len(latest) == 1
    assert latest[0].date == new
    assert float(latest[0].value) == 60.0


def test_get_latest_empty_for_unknown_symbol(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    assert repo.get_latest_for_symbol("NOPE") == []


def test_get_range_filters_by_indicator(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    d1 = date(2024, 12, 30)
    d2 = date(2024, 12, 31)
    repo.upsert_many(
        [
            result_to_row("AAPL", d1, _make_result("rsi", value=40.0)),
            result_to_row("AAPL", d1, _make_result("macd", value=1.0)),
            result_to_row("AAPL", d2, _make_result("rsi", value=45.0)),
        ]
    )
    db_session.commit()

    only_rsi = repo.get_range("AAPL", start_date=d1, end_date=d2, indicator_name="rsi")
    assert [r.indicator_name for r in only_rsi] == ["rsi", "rsi"]

    all_rows = repo.get_range("AAPL", start_date=d1, end_date=d2)
    assert len(all_rows) == 3


def test_null_value_is_persisted(db_session: Session) -> None:
    repo = DailySignalRepository(db_session)
    today = date(2024, 12, 31)
    result = IndicatorResult(
        name="rsi",
        value=None,
        signal=SignalTone.NEUTRAL,  # type: ignore[arg-type]
        data_sufficient=False,
        short_label="資料不足",
        detail={},
        computed_at=datetime.now(UTC),
    )
    repo.upsert_many([result_to_row("AAPL", today, result)])
    db_session.commit()
    stored = repo.get_latest_for_symbol("AAPL")
    assert stored[0].value is None
    assert stored[0].data_sufficient is False

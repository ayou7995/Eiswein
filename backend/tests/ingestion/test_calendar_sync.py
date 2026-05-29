"""calendar_sync — end-to-end orchestrator (mocked feeds)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.calendar_event_repository import (
    CalendarEventRepository,
    CalendarEventRow,
)
from app.ingestion.calendar_sync import run_calendar_sync


def _row(**overrides: object) -> CalendarEventRow:
    base: CalendarEventRow = CalendarEventRow(
        event_date=date(2026, 6, 15),
        event_time=None,
        type="earnings",
        ticker_symbol="AAPL",
        title="AAPL Earnings",
        payload_json=None,
        source="yfinance",
    )
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


@pytest.fixture
def yaml_path(tmp_path: Path) -> Path:
    p = tmp_path / "events.yaml"
    p.write_text("[]\n", encoding="utf-8")
    return p


async def test_run_calendar_sync_unions_three_sources(db_session: Session, yaml_path: Path) -> None:
    earnings = [_row(ticker_symbol="AAPL", title="AAPL Earnings")]
    macro = [
        _row(
            event_date=date(2026, 6, 12),
            type="macro",
            ticker_symbol=None,
            title="CPI Release",
            source="hardcoded",
        )
    ]
    industry = [
        _row(
            event_date=date(2026, 6, 9),
            type="industry",
            ticker_symbol="AAPL",
            title="WWDC Keynote",
            source="yaml",
        )
    ]
    with (
        patch(
            "app.ingestion.calendar_sync.fetch_earnings_for_symbols",
            return_value=earnings,
        ),
        patch(
            "app.ingestion.calendar_sync.generate_macro_release_schedule",
            return_value=macro,
        ),
        patch(
            "app.ingestion.calendar_sync.load_industry_events_from_yaml",
            return_value=industry,
        ),
    ):
        result = await run_calendar_sync(
            db_session,
            watchlist_symbols=["AAPL"],
            yaml_path=yaml_path,
            as_of=date(2026, 6, 1),
        )
    assert result.earnings_count == 1
    assert result.macro_count == 1
    assert result.industry_count == 1
    assert result.total_upserted == 3
    assert result.orphans_deleted == 0

    rows = CalendarEventRepository(db_session).list_in_range(
        start=date(2026, 6, 1), end=date(2026, 6, 30)
    )
    titles = {r.title for r in rows}
    assert titles == {"AAPL Earnings", "CPI Release", "WWDC Keynote"}


async def test_run_calendar_sync_fault_isolated_earnings(
    db_session: Session, yaml_path: Path
) -> None:
    """yfinance outage must not break macro + industry feeds."""
    macro = [
        _row(
            event_date=date(2026, 6, 12),
            type="macro",
            ticker_symbol=None,
            title="CPI Release",
            source="hardcoded",
        )
    ]
    with (
        patch(
            "app.ingestion.calendar_sync.fetch_earnings_for_symbols",
            side_effect=RuntimeError("upstream dead"),
        ),
        patch(
            "app.ingestion.calendar_sync.generate_macro_release_schedule",
            return_value=macro,
        ),
        patch(
            "app.ingestion.calendar_sync.load_industry_events_from_yaml",
            return_value=[],
        ),
    ):
        result = await run_calendar_sync(
            db_session,
            watchlist_symbols=["AAPL"],
            yaml_path=yaml_path,
        )
    assert result.earnings_count == 0
    assert result.macro_count == 1
    assert result.total_upserted == 1


async def test_run_calendar_sync_is_idempotent(db_session: Session, yaml_path: Path) -> None:
    """Re-running the sync produces no duplicate rows."""
    rows_in = [
        _row(),
        _row(
            event_date=date(2026, 6, 12),
            type="macro",
            ticker_symbol=None,
            title="CPI Release",
            source="hardcoded",
        ),
    ]
    with (
        patch(
            "app.ingestion.calendar_sync.fetch_earnings_for_symbols",
            return_value=[rows_in[0]],
        ),
        patch(
            "app.ingestion.calendar_sync.generate_macro_release_schedule",
            return_value=[rows_in[1]],
        ),
        patch(
            "app.ingestion.calendar_sync.load_industry_events_from_yaml",
            return_value=[],
        ),
    ):
        await run_calendar_sync(db_session, watchlist_symbols=["AAPL"], yaml_path=yaml_path)
        await run_calendar_sync(db_session, watchlist_symbols=["AAPL"], yaml_path=yaml_path)

    rows = CalendarEventRepository(db_session).list_in_range(
        start=date(2026, 6, 1), end=date(2026, 6, 30)
    )
    assert len(rows) == 2


async def test_run_calendar_sync_purges_orphans_for_removed_tickers(
    db_session: Session, yaml_path: Path
) -> None:
    """A symbol that left the watchlist gets its earnings events
    purged on the next sync (macro events untouched)."""
    # First run: AAPL + MSFT in watchlist.
    with (
        patch(
            "app.ingestion.calendar_sync.fetch_earnings_for_symbols",
            return_value=[
                _row(ticker_symbol="AAPL", title="AAPL Earnings"),
                _row(ticker_symbol="MSFT", title="MSFT Earnings"),
            ],
        ),
        patch(
            "app.ingestion.calendar_sync.generate_macro_release_schedule",
            return_value=[
                _row(
                    event_date=date(2026, 6, 12),
                    type="macro",
                    ticker_symbol=None,
                    title="CPI Release",
                    source="hardcoded",
                )
            ],
        ),
        patch(
            "app.ingestion.calendar_sync.load_industry_events_from_yaml",
            return_value=[],
        ),
    ):
        await run_calendar_sync(db_session, watchlist_symbols=["AAPL", "MSFT"], yaml_path=yaml_path)

    # Second run: MSFT dropped from watchlist; fetch only returns AAPL.
    with (
        patch(
            "app.ingestion.calendar_sync.fetch_earnings_for_symbols",
            return_value=[_row(ticker_symbol="AAPL", title="AAPL Earnings")],
        ),
        patch(
            "app.ingestion.calendar_sync.generate_macro_release_schedule",
            return_value=[],
        ),
        patch(
            "app.ingestion.calendar_sync.load_industry_events_from_yaml",
            return_value=[],
        ),
    ):
        result = await run_calendar_sync(
            db_session, watchlist_symbols=["AAPL"], yaml_path=yaml_path
        )

    assert result.orphans_deleted == 1
    titles = {
        r.title
        for r in CalendarEventRepository(db_session).list_in_range(
            start=date(2026, 6, 1), end=date(2026, 6, 30)
        )
    }
    assert "MSFT Earnings" not in titles
    assert "AAPL Earnings" in titles
    assert "CPI Release" in titles  # macro untouched

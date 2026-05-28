"""CalendarEventRepository — upsert idempotency + range queries + orphan purge."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.repositories.calendar_event_repository import (
    CalendarEventRepository,
    CalendarEventRow,
)


def _earnings_row(symbol: str, day: date, time_marker: str | None = "AMC") -> CalendarEventRow:
    return CalendarEventRow(
        event_date=day,
        event_time=time_marker,
        type="earnings",
        ticker_symbol=symbol,
        title=f"{symbol} Earnings",
        payload_json={"time_marker": time_marker} if time_marker else None,
        source="yfinance",
    )


def _macro_row(day: date, title: str = "CPI Release") -> CalendarEventRow:
    return CalendarEventRow(
        event_date=day,
        event_time="8:30 ET",
        type="macro",
        ticker_symbol=None,
        title=title,
        payload_json=None,
        source="hardcoded",
    )


def test_upsert_inserts_new_rows(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    inserted = repo.upsert_many(
        [
            _earnings_row("AAPL", date(2026, 6, 1)),
            _macro_row(date(2026, 6, 12)),
        ]
    )
    assert inserted == 2
    rows = repo.list_in_range(start=date(2026, 6, 1), end=date(2026, 6, 30))
    assert len(rows) == 2
    assert {r.title for r in rows} == {"AAPL Earnings", "CPI Release"}


def test_upsert_idempotent_on_natural_key(db_session: Session) -> None:
    """Running sync twice with same rows produces one DB row each."""
    repo = CalendarEventRepository(db_session)
    repo.upsert_many([_earnings_row("AAPL", date(2026, 6, 1), "BMO")])
    repo.upsert_many([_earnings_row("AAPL", date(2026, 6, 1), "AMC")])

    rows = repo.list_in_range(start=date(2026, 6, 1), end=date(2026, 6, 1))
    assert len(rows) == 1
    # Conflict branch refreshed event_time + payload to the latest values.
    assert rows[0].event_time == "AMC"
    assert rows[0].payload_json == {"time_marker": "AMC"}


def test_upsert_distinguishes_macro_events_with_different_titles(
    db_session: Session,
) -> None:
    """Two macro events on the same date with different titles must
    coexist — the dedup index includes ``title``, not just (date, type)."""
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _macro_row(date(2026, 6, 12), title="CPI Release"),
            _macro_row(date(2026, 6, 12), title="PPI Release"),
        ]
    )
    rows = repo.list_in_range(start=date(2026, 6, 12), end=date(2026, 6, 12))
    assert {r.title for r in rows} == {"CPI Release", "PPI Release"}


def test_list_in_range_excludes_outside_window(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _earnings_row("NVDA", date(2026, 5, 30)),
            _earnings_row("NVDA", date(2026, 6, 5)),
            _earnings_row("NVDA", date(2026, 7, 1)),
        ]
    )
    rows = repo.list_in_range(start=date(2026, 6, 1), end=date(2026, 6, 30))
    assert len(rows) == 1
    assert rows[0].event_date == date(2026, 6, 5)


def test_list_in_range_filters_by_type(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _earnings_row("AAPL", date(2026, 6, 1)),
            _macro_row(date(2026, 6, 12)),
        ]
    )
    rows = repo.list_in_range(
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        types=["macro"],
    )
    assert len(rows) == 1
    assert rows[0].type == "macro"


def test_list_in_range_with_ticker_filter_keeps_macro(db_session: Session) -> None:
    """When the caller filters by ticker (e.g. 'just my EV stocks'),
    macro events must still appear — losing CPI because the operator
    filtered for 'EV' would be a UX trap."""
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _earnings_row("AAPL", date(2026, 6, 1)),
            _earnings_row("NVDA", date(2026, 6, 3)),
            _macro_row(date(2026, 6, 12)),
        ]
    )
    rows = repo.list_in_range(
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        ticker_symbols=["NVDA"],
    )
    titles = {r.title for r in rows}
    assert "NVDA Earnings" in titles
    assert "CPI Release" in titles
    assert "AAPL Earnings" not in titles


def test_next_for_ticker_returns_earliest_upcoming(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _earnings_row("TSLA", date(2026, 5, 1)),  # past
            _earnings_row("TSLA", date(2026, 7, 15)),  # future
            _earnings_row("TSLA", date(2026, 10, 1)),  # further future
        ]
    )
    nxt = repo.next_for_ticker(ticker_symbol="TSLA", as_of=date(2026, 6, 1))
    assert nxt is not None
    assert nxt.event_date == date(2026, 7, 15)


def test_next_for_ticker_returns_none_when_no_upcoming(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many([_earnings_row("TSLA", date(2026, 5, 1))])
    assert repo.next_for_ticker(ticker_symbol="TSLA", as_of=date(2026, 6, 1)) is None


def test_upcoming_macro_within_window(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _macro_row(date(2026, 6, 12), title="CPI Release"),
            _macro_row(date(2026, 6, 20), title="FOMC Meeting"),
            _macro_row(date(2026, 7, 15), title="CPI Release"),  # beyond window
            _earnings_row("AAPL", date(2026, 6, 13)),  # not macro
        ]
    )
    rows = repo.upcoming_macro(as_of=date(2026, 6, 10), days=14)
    titles = [r.title for r in rows]
    assert titles == ["CPI Release", "FOMC Meeting"]


def test_delete_orphans_drops_earnings_for_removed_symbols(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many(
        [
            _earnings_row("AAPL", date(2026, 6, 1)),
            _earnings_row("MSFT", date(2026, 6, 2)),
            _macro_row(date(2026, 6, 12)),
        ]
    )
    deleted = repo.delete_orphans_for_symbols(["MSFT"])
    assert deleted == 1
    rows = repo.list_in_range(start=date(2026, 6, 1), end=date(2026, 6, 30))
    titles = {r.title for r in rows}
    assert "MSFT Earnings" not in titles
    # Macro events untouched.
    assert "CPI Release" in titles
    # AAPL kept.
    assert "AAPL Earnings" in titles


def test_delete_orphans_skips_when_no_input(db_session: Session) -> None:
    repo = CalendarEventRepository(db_session)
    repo.upsert_many([_earnings_row("AAPL", date(2026, 6, 1))])
    assert repo.delete_orphans_for_symbols([]) == 0

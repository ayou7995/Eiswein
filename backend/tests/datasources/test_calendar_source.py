"""calendar_source — YAML loader + macro release rule generator.

yfinance earnings fetch is exercised only at the contract level (one
test verifies the per-symbol fault isolation by mocking the inner
helper); the real upstream is not hit in CI.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.datasources.calendar_source import (
    _classify_earnings_time,
    _first_weekday_of_month,
    _last_business_day,
    fetch_earnings_for_symbols,
    generate_macro_release_schedule,
    load_industry_events_from_yaml,
)
from app.db.repositories.calendar_event_repository import CalendarEventRow

# --- YAML loader ----------------------------------------------------------


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "events.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_yaml_missing_file_returns_empty(tmp_path: Path) -> None:
    rows = load_industry_events_from_yaml(tmp_path / "nope.yaml")
    assert rows == []


def test_load_yaml_empty_list_returns_empty(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "[]\n")
    assert load_industry_events_from_yaml(path) == []


def test_load_yaml_parses_full_entry(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
        - date: 2026-06-09
          title: AAPL WWDC Keynote
          ticker: aapl
          time: "10:00 PT"
          tags: [AI, Hardware]
        """,
    )
    rows = load_industry_events_from_yaml(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["event_date"] == date(2026, 6, 9)
    assert row["title"] == "AAPL WWDC Keynote"
    assert row["ticker_symbol"] == "AAPL"
    assert row["event_time"] == "10:00 PT"
    assert row["type"] == "industry"
    assert row["source"] == "yaml"
    assert row["payload_json"] == {"tags": ["AI", "Hardware"]}


def test_load_yaml_ticker_optional(tmp_path: Path) -> None:
    """Sector-wide events omit ``ticker``; row gets None."""
    path = _write_yaml(
        tmp_path,
        """
        - date: 2026-07-15
          title: SpaceX IPO filing window
        """,
    )
    rows = load_industry_events_from_yaml(path)
    assert rows[0]["ticker_symbol"] is None


def test_load_yaml_skips_malformed_entries(tmp_path: Path) -> None:
    """One bad entry should not crash the whole sync."""
    path = _write_yaml(
        tmp_path,
        """
        - date: 2026-06-09
          title: Good entry
        - not a dict
        - date: invalid-date
          title: Bad date
        - title: Missing date
        - date: 2026-06-15
          # missing title
        """,
    )
    rows = load_industry_events_from_yaml(path)
    assert len(rows) == 1
    assert rows[0]["title"] == "Good entry"


def test_load_yaml_parse_error_returns_empty(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, ":\n:")  # invalid YAML
    assert load_industry_events_from_yaml(path) == []


# --- Macro release schedule -----------------------------------------------


def _events_with_title(rows: Iterable[CalendarEventRow], title: str) -> list[CalendarEventRow]:
    return [r for r in rows if r["title"] == title]


def test_macro_schedule_returns_empty_for_inverted_range() -> None:
    rows = generate_macro_release_schedule(date(2026, 7, 1), date(2026, 6, 1))
    assert rows == []


def test_macro_schedule_emits_one_cpi_per_month() -> None:
    rows = generate_macro_release_schedule(date(2026, 6, 1), date(2026, 8, 31))
    cpi = _events_with_title(rows, "CPI Release")
    # Three months * one CPI per month = 3 events.
    assert len(cpi) == 3
    months = sorted({r["event_date"].month for r in cpi})
    assert months == [6, 7, 8]


def test_macro_schedule_nfp_lands_on_friday() -> None:
    rows = generate_macro_release_schedule(date(2026, 6, 1), date(2026, 6, 30))
    nfp = _events_with_title(rows, "Non-Farm Payrolls")
    assert len(nfp) == 1
    assert nfp[0]["event_date"].weekday() == 4  # Friday


def test_macro_schedule_pce_lands_on_business_day() -> None:
    """PCE = last business day of the month; weekends are bumped back."""
    rows = generate_macro_release_schedule(date(2026, 7, 1), date(2026, 7, 31))
    pce = _events_with_title(rows, "PCE Release")
    assert len(pce) == 1
    # 2026-07-31 is a Friday — should pick exactly that day.
    assert pce[0]["event_date"] == date(2026, 7, 31)


def test_macro_schedule_bumps_weekend_releases_to_monday() -> None:
    """CPI on the 13th — when 13th is a Saturday it must bump to Monday 15th."""
    # September 2026: 13 is a Sunday.
    rows = generate_macro_release_schedule(date(2026, 9, 1), date(2026, 9, 30))
    cpi = _events_with_title(rows, "CPI Release")
    assert len(cpi) == 1
    # Sun 13 → Mon 14 — confirm weekday is Monday.
    assert cpi[0]["event_date"].weekday() == 0


def test_macro_schedule_includes_fomc_when_in_range() -> None:
    rows = generate_macro_release_schedule(date(2026, 1, 1), date(2026, 3, 31))
    fomc = _events_with_title(rows, "FOMC Meeting")
    # 2026 FOMC meetings in Q1: Jan 28, Mar 18.
    dates = sorted(r["event_date"] for r in fomc)
    assert dates == [date(2026, 1, 28), date(2026, 3, 18)]


def test_macro_schedule_all_rows_are_macro_type() -> None:
    rows = generate_macro_release_schedule(date(2026, 6, 1), date(2026, 6, 30))
    assert {r["type"] for r in rows} == {"macro"}
    assert all(r["ticker_symbol"] is None for r in rows)


def test_macro_schedule_no_duplicates_in_single_month() -> None:
    """Sanity: each (date, title) pair is unique within the result."""
    rows = generate_macro_release_schedule(date(2026, 6, 1), date(2026, 6, 30))
    keys = [(r["event_date"], r["title"]) for r in rows]
    assert len(keys) == len(set(keys))


# --- Helpers --------------------------------------------------------------


def test_first_weekday_of_month_finds_first_friday() -> None:
    # June 2026: 1st is a Monday; first Friday is the 5th.
    assert _first_weekday_of_month(date(2026, 6, 1), weekday=4) == date(2026, 6, 5)


def test_last_business_day_walks_back_from_weekend() -> None:
    # 2026-08-31 is a Monday → unchanged.
    assert _last_business_day(date(2026, 8, 31)) == date(2026, 8, 31)
    # 2026-05-31 is a Sunday → 2026-05-29 (Friday).
    assert _last_business_day(date(2026, 5, 31)) == date(2026, 5, 29)


def test_classify_earnings_time_marks_premarket_postmarket() -> None:
    from datetime import datetime

    pre = datetime(2026, 5, 27, 7, 30, tzinfo=UTC)
    after = datetime(2026, 5, 27, 16, 30, tzinfo=UTC)
    midday = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    assert _classify_earnings_time(pre) == "BMO"
    assert _classify_earnings_time(after) == "AMC"
    assert _classify_earnings_time(midday) is None


# --- yfinance earnings (mock-only) -----------------------------------------


async def test_fetch_earnings_empty_symbols_short_circuits() -> None:
    out = await fetch_earnings_for_symbols([])
    assert out == []


async def test_fetch_earnings_per_symbol_fault_isolated() -> None:
    """One symbol blowing up must not break the others."""

    def fake_fetch(
        symbol: str,
        *,
        cutoff_start: date,
        cutoff_end: date,
    ) -> list[CalendarEventRow]:
        if symbol == "BROKEN":
            raise RuntimeError("yfinance hiccup")
        return [
            CalendarEventRow(
                event_date=date(2026, 6, 15),
                event_time="AMC",
                type="earnings",
                ticker_symbol=symbol,
                title=f"{symbol} Earnings",
                payload_json=None,
                source="yfinance",
            )
        ]

    with patch(
        "app.datasources.calendar_source._fetch_single_symbol_earnings",
        side_effect=fake_fetch,
    ):
        out = await fetch_earnings_for_symbols(["AAPL", "BROKEN", "NVDA"])

    symbols = sorted(r["ticker_symbol"] for r in out)
    assert symbols == ["AAPL", "NVDA"]


@pytest.fixture(autouse=False)
def _stub_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive stub — never call real yfinance from tests."""

    class _NotImplemented:
        def get_earnings_dates(self, **_: Any) -> None:
            raise AssertionError("yfinance must be mocked at the inner level")

    monkeypatch.setattr("app.datasources.calendar_source.yf.Ticker", _NotImplemented)

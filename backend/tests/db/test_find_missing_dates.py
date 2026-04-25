"""DailyPriceRepository.find_missing_dates + find_gaps_for_symbols — gap detection."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.daily_price_repository import DailyPriceRepository, DailyPriceRow
from app.ingestion.market_calendar import get_trading_days

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(symbol: str, day: date) -> DailyPriceRow:
    return DailyPriceRow(
        symbol=symbol,
        date=day,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.50"),
        volume=1_000_000,
    )


def _trading_days_ending(end: date, count: int) -> list[date]:
    """Return the last ``count`` NYSE sessions up to and including ``end``."""
    # 3x buffer is enough to guarantee ``count`` sessions across any span.
    start = end - timedelta(days=count * 3)
    sessions = get_trading_days(start, end)
    return sessions[-count:]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _pin_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin 'today' to a known Monday so tests are calendar-independent.

    2026-04-20 is a regular Monday — not a holiday, not a weekend.
    We pin both ``today_et`` (used internally) and ``last_trading_day_et``
    (which the repository calls to anchor the lookback window).
    """
    fixed = date(2026, 4, 20)
    monkeypatch.setattr(
        "app.db.repositories.daily_price_repository.today_et",
        lambda: fixed,
    )
    monkeypatch.setattr(
        "app.db.repositories.daily_price_repository.last_trading_day_et",
        lambda reference=None: reference if reference is not None else fixed,
    )
    return fixed


# ---------------------------------------------------------------------------
# find_missing_dates
# ---------------------------------------------------------------------------


def test_find_missing_dates_returns_three_gaps(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    lookback = 20
    end = _pin_today  # 2026-04-20

    all_sessions = _trading_days_ending(end, lookback)
    assert len(all_sessions) == lookback

    # Pick 3 non-consecutive positions to skip (indices 5, 10, 15).
    gap_indices = {5, 10, 15}
    gap_dates = {all_sessions[i] for i in gap_indices}
    present_dates = [d for d in all_sessions if d not in gap_dates]

    repo.upsert_many([_make_row("SPY", d) for d in present_dates])

    missing = repo.find_missing_dates("SPY", lookback_days=lookback)

    assert sorted(missing) == sorted(gap_dates)
    # Must be sorted ascending
    assert missing == sorted(missing)
    # No weekends in result
    for d in missing:
        assert d.weekday() < 5, f"Weekend in missing list: {d}"


def test_find_missing_dates_all_present_returns_empty(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    lookback = 5
    end = _pin_today

    sessions = _trading_days_ending(end, lookback)
    repo.upsert_many([_make_row("SPY", d) for d in sessions])

    missing = repo.find_missing_dates("SPY", lookback_days=lookback)
    assert missing == []


def test_find_missing_dates_no_rows_returns_full_window(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    lookback = 10

    # No rows for ZZZZ at all.
    missing = repo.find_missing_dates("ZZZZ", lookback_days=lookback)
    assert len(missing) == lookback
    for d in missing:
        assert d.weekday() < 5


def test_find_missing_dates_lookback_bound_excludes_older_gaps(
    db_session: Session,
    _pin_today: date,
) -> None:
    """Gaps older than the lookback window must not appear in results."""
    repo = DailyPriceRepository(db_session)
    lookback = 10
    full_lookback = 60
    end = _pin_today

    # Get the 60-session window and insert only the most-recent 10 sessions.
    all_60 = _trading_days_ending(end, full_lookback)
    recent_10 = all_60[-lookback:]
    old_50 = all_60[:-lookback]

    # Insert the recent 10 so they're present; the old 50 are missing.
    repo.upsert_many([_make_row("SPY", d) for d in recent_10])

    # With lookback_days=10, only the window covering the 10 recent sessions
    # is considered — all 10 are present → zero gaps reported.
    missing = repo.find_missing_dates("SPY", lookback_days=lookback)
    assert missing == []

    # With lookback_days=60 we see the old gaps too.
    missing_60 = repo.find_missing_dates("SPY", lookback_days=full_lookback)
    # All of old_50 should be missing (ZZZZ symbol has none inserted there).
    for d in old_50:
        assert d in missing_60


# ---------------------------------------------------------------------------
# find_gaps_for_symbols
# ---------------------------------------------------------------------------


def test_find_gaps_for_symbols_returns_entry_per_symbol(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    lookback = 10
    end = _pin_today

    sessions = _trading_days_ending(end, lookback)

    # SPY: all present → no gaps.
    repo.upsert_many([_make_row("SPY", d) for d in sessions])

    # QQQ: missing the last 2 sessions.
    qqq_present = sessions[:-2]
    qqq_gaps = sessions[-2:]
    repo.upsert_many([_make_row("QQQ", d) for d in qqq_present])

    # ZZZZ: no rows at all → full window gap.

    result = repo.find_gaps_for_symbols(["SPY", "QQQ", "ZZZZ"], lookback_days=lookback)

    assert set(result.keys()) == {"SPY", "QQQ", "ZZZZ"}
    assert result["SPY"] == []
    assert sorted(result["QQQ"]) == sorted(qqq_gaps)
    assert len(result["ZZZZ"]) == lookback


def test_find_gaps_for_symbols_is_sorted_ascending_per_symbol(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    lookback = 15
    end = _pin_today

    sessions = _trading_days_ending(end, lookback)
    # Leave 5 gaps scattered across SPY.
    gap_set = {sessions[2], sessions[7], sessions[12]}
    present = [d for d in sessions if d not in gap_set]
    repo.upsert_many([_make_row("SPY", d) for d in present])

    result = repo.find_gaps_for_symbols(["SPY"], lookback_days=lookback)
    spy_gaps = result["SPY"]
    assert spy_gaps == sorted(spy_gaps)


def test_find_gaps_for_symbols_empty_input_returns_empty_dict(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    assert repo.find_gaps_for_symbols([]) == {}


def test_find_gaps_for_symbols_zero_lookback_returns_all_empty(
    db_session: Session,
    _pin_today: date,
) -> None:
    repo = DailyPriceRepository(db_session)
    result = repo.find_gaps_for_symbols(["SPY"], lookback_days=0)
    assert result == {"SPY": []}

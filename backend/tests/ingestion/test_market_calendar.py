"""market_calendar.get_trading_days — NYSE session list, holiday exclusion, edge cases."""

from __future__ import annotations

from datetime import date

from app.ingestion.market_calendar import get_trading_days


def test_market_calendar_regular_week_excludes_weekends() -> None:
    # 2026-04-13 (Mon) → 2026-04-17 (Fri) — plain 5-session week.
    days = get_trading_days(date(2026, 4, 13), date(2026, 4, 17))
    assert len(days) == 5
    for d in days:
        # 0=Mon … 4=Fri; 5=Sat, 6=Sun
        assert d.weekday() < 5, f"Weekend slipped through: {d}"


def test_market_calendar_ten_weekdays_returns_ten() -> None:
    # 2026-01-05 (Mon) → 2026-01-16 (Fri) spans 2 full weeks → 10 sessions.
    days = get_trading_days(date(2026, 1, 5), date(2026, 1, 16))
    assert len(days) == 10
    # Sorted ascending
    assert days == sorted(days)


def test_market_calendar_thanksgiving_excluded() -> None:
    # 2024-11-28 is Thanksgiving (NYSE closed).
    # Ask for the full week: Mon 11-25 → Fri 11-29 (also early close / Friday).
    # Friday after Thanksgiving (2024-11-29) is a half-session but still a trading day.
    days = get_trading_days(date(2024, 11, 25), date(2024, 11, 29))
    assert date(2024, 11, 28) not in days, "Thanksgiving should not appear"
    # Mon–Wed should be present
    assert date(2024, 11, 25) in days
    assert date(2024, 11, 26) in days
    assert date(2024, 11, 27) in days


def test_market_calendar_new_year_2025_excluded() -> None:
    # 2025-01-01 is New Year's Day — NYSE closed.
    days = get_trading_days(date(2025, 1, 1), date(2025, 1, 1))
    assert days == [], "New Year's Day is not a trading day"


def test_market_calendar_end_before_start_returns_empty() -> None:
    days = get_trading_days(date(2026, 4, 10), date(2026, 4, 9))
    assert days == []


def test_market_calendar_same_day_trading_day_returns_one() -> None:
    # 2026-04-20 is a Monday (Good Friday is 4-3; Easter Monday is not an NYSE holiday).
    # Use a safe Monday that is definitely not a holiday.
    days = get_trading_days(date(2026, 4, 20), date(2026, 4, 20))
    assert len(days) == 1
    assert days[0] == date(2026, 4, 20)


def test_market_calendar_same_day_weekend_returns_empty() -> None:
    # 2026-04-18 is a Saturday.
    days = get_trading_days(date(2026, 4, 18), date(2026, 4, 18))
    assert days == []


def test_market_calendar_result_contains_only_date_objects() -> None:
    days = get_trading_days(date(2026, 4, 14), date(2026, 4, 14))
    for d in days:
        assert isinstance(d, date)

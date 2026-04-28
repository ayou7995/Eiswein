"""market_calendar.get_trading_days — NYSE session list, holiday exclusion, edge cases."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from app.ingestion.market_calendar import (
    get_trading_days,
    is_intraday_partial,
    is_post_close_et,
    nyse_close_at_et,
)

_ET = ZoneInfo("America/New_York")


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


# --- nyse_close_at_et / is_post_close_et / is_intraday_partial ---


def test_nyse_close_at_et_returns_16_00_on_regular_session() -> None:
    close = nyse_close_at_et(date(2026, 4, 14))  # Tuesday, regular session
    assert close is not None
    assert close.tzinfo is not None
    # Regular sessions close at 16:00 ET.
    assert (close.hour, close.minute) == (16, 0)


def test_nyse_close_at_et_returns_none_on_weekend() -> None:
    # 2026-04-18 is a Saturday.
    assert nyse_close_at_et(date(2026, 4, 18)) is None


def test_nyse_close_at_et_returns_none_on_holiday() -> None:
    # 2025-01-01 is a NYSE holiday.
    assert nyse_close_at_et(date(2025, 1, 1)) is None


def test_nyse_close_at_et_honours_early_close() -> None:
    # Black Friday 2024-11-29 is an NYSE early-close day (13:00 ET).
    close = nyse_close_at_et(date(2024, 11, 29))
    assert close is not None
    assert (close.hour, close.minute) == (13, 0)


def test_is_post_close_et_false_pre_close() -> None:
    # 14:00 ET on a regular Tuesday — well before 16:00 close.
    with freeze_time(datetime(2026, 4, 14, 14, 0, tzinfo=_ET)):
        assert is_post_close_et() is False


def test_is_post_close_et_false_within_buffer() -> None:
    # 16:15 ET — past close but inside the 30-min buffer.
    with freeze_time(datetime(2026, 4, 14, 16, 15, tzinfo=_ET)):
        assert is_post_close_et() is False


def test_is_post_close_et_true_past_buffer() -> None:
    # 16:35 ET — five minutes past 16:00 + 30 buffer.
    with freeze_time(datetime(2026, 4, 14, 16, 35, tzinfo=_ET)):
        assert is_post_close_et() is True


def test_is_post_close_et_false_on_weekend() -> None:
    # Saturday — no close, so never post-close.
    with freeze_time(datetime(2026, 4, 18, 23, 59, tzinfo=_ET)):
        assert is_post_close_et() is False


def test_is_post_close_et_custom_buffer() -> None:
    # 16:05 ET with buffer=2 → past close+2min, expect True.
    with freeze_time(datetime(2026, 4, 14, 16, 5, tzinfo=_ET)):
        assert is_post_close_et(buffer_minutes=2) is True


def test_is_intraday_partial_pre_close_today() -> None:
    # Mid-session: row written at 14:00 ET today, asking at 14:00 ET.
    today = date(2026, 4, 14)
    write_time = datetime(2026, 4, 14, 14, 0, tzinfo=_ET)
    with freeze_time(write_time):
        assert is_intraday_partial(row_date=today, row_updated_at=write_time) is True


def test_is_intraday_partial_post_close_today() -> None:
    # Today's session, but row was written at 17:00 ET (past close+buffer).
    today = date(2026, 4, 14)
    write_time = datetime(2026, 4, 14, 17, 0, tzinfo=_ET)
    with freeze_time(write_time + timedelta(minutes=1)):
        assert is_intraday_partial(row_date=today, row_updated_at=write_time) is False


def test_is_intraday_partial_yesterday_never_intraday() -> None:
    # Even if yesterday's row was somehow written pre-close, it's not
    # "today" any more — partial-bar logic only ever cares about today.
    yesterday = date(2026, 4, 13)
    write_time = datetime(2026, 4, 13, 14, 0, tzinfo=_ET)
    with freeze_time(datetime(2026, 4, 14, 10, 0, tzinfo=_ET)):
        assert is_intraday_partial(row_date=yesterday, row_updated_at=write_time) is False


def test_is_intraday_partial_weekend_today_returns_false() -> None:
    # If today is a weekend, no close exists → no row can be intraday.
    saturday = date(2026, 4, 18)
    write_time = datetime(2026, 4, 18, 12, 0, tzinfo=_ET)
    with freeze_time(write_time):
        assert is_intraday_partial(row_date=saturday, row_updated_at=write_time) is False


def test_is_intraday_partial_naive_timestamp_treated_as_utc() -> None:
    # The repository writes UTC-naive timestamps in some legacy paths;
    # the helper should treat naive datetimes as UTC and not crash.
    today = date(2026, 4, 14)
    write_naive_utc = datetime(2026, 4, 14, 18, 0)  # 14:00 ET == 18:00 UTC
    with freeze_time(datetime(2026, 4, 14, 18, 1, tzinfo=ZoneInfo("UTC"))):
        # 14:00 ET write → still pre-close, so intraday-partial.
        assert is_intraday_partial(row_date=today, row_updated_at=write_naive_utc) is True


@pytest.mark.parametrize(
    "label,row_dt,now_dt,expect",
    [
        (
            "row=10:00 ET, now=11:00 ET → partial",
            datetime(2026, 4, 14, 10, 0, tzinfo=_ET),
            datetime(2026, 4, 14, 11, 0, tzinfo=_ET),
            True,
        ),
        (
            "row=15:55 ET, now=15:56 ET → still partial (close not yet)",
            datetime(2026, 4, 14, 15, 55, tzinfo=_ET),
            datetime(2026, 4, 14, 15, 56, tzinfo=_ET),
            True,
        ),
        (
            "row=16:00 ET (right at close), now=16:31 ET → still partial (row < close+buffer)",
            datetime(2026, 4, 14, 16, 0, tzinfo=_ET),
            datetime(2026, 4, 14, 16, 31, tzinfo=_ET),
            True,
        ),
        (
            "row=16:31 ET (past buffer), now=16:32 ET → settled",
            datetime(2026, 4, 14, 16, 31, tzinfo=_ET),
            datetime(2026, 4, 14, 16, 32, tzinfo=_ET),
            False,
        ),
    ],
)
def test_is_intraday_partial_table(
    label: str,
    row_dt: datetime,
    now_dt: datetime,
    expect: bool,
) -> None:
    today = date(2026, 4, 14)
    with freeze_time(now_dt):
        assert is_intraday_partial(row_date=today, row_updated_at=row_dt) is expect, label

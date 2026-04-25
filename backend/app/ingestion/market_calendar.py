"""NYSE market calendar wrapper (I6).

``daily_update`` must skip weekends and holidays — running on a
non-trading day either produces stale duplicates (idempotency holds
but wastes a yfinance call) or outright errors when the market was
closed.

Wrapped as a module-level function so tests can monkeypatch it without
mocking ``pandas_market_calendars`` internals.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")
_MARKET_TZ = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(_MARKET_TZ)


def today_et() -> date:
    return now_et().date()


def is_trading_day_et(day: date | None = None) -> bool:
    """True iff ``day`` is a valid NYSE session.

    Default is the current ET date, matching how the scheduler job
    will call it at 06:30 ET.
    """
    target = day or today_et()
    schedule = _NYSE.schedule(start_date=target, end_date=target)
    return not schedule.empty


def last_trading_day_et(*, reference: date | None = None) -> date:
    """Most recent trading day on or before ``reference``.

    Used by the UI label "最近交易日: YYYY-MM-DD" so weekends show the
    preceding Friday rather than today's weekend date.
    """
    ref = reference or today_et()
    schedule = _NYSE.schedule(start_date=ref - pd.Timedelta(days=10), end_date=ref)
    if schedule.empty:
        return ref
    last = schedule.index[-1]
    if isinstance(last, pd.Timestamp):
        return last.date()
    return ref


def get_trading_days(start: date, end: date) -> list[date]:
    """NYSE trading days in ``[start, end]`` inclusive, ascending.

    Used by the gap-aware daily-update flow to compute which dates we
    *expected* price rows for. Anything missing from DailyPrice within
    that set is a real gap (weekends + market holidays never show up
    here, so they are never reported as gaps).

    Returns plain ``date`` objects — not timestamps — so callers can
    diff against DailyPrice.date without tz/time coercion quirks.
    Empty list when ``end < start`` or the span contains no session.
    """
    if end < start:
        return []
    schedule = _NYSE.schedule(start_date=start, end_date=end)
    if schedule.empty:
        return []
    days: list[date] = []
    for ts in schedule.index:
        if isinstance(ts, pd.Timestamp):
            days.append(ts.date())
    days.sort()
    return days

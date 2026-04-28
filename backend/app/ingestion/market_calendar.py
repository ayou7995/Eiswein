"""NYSE market calendar wrapper (I6).

``daily_update`` must skip weekends and holidays — running on a
non-trading day either produces stale duplicates (idempotency holds
but wastes a yfinance call) or outright errors when the market was
closed.

Wrapped as a module-level function so tests can monkeypatch it without
mocking ``pandas_market_calendars`` internals.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")
_MARKET_TZ = ZoneInfo("America/New_York")

# Buffer past NYSE close before we consider a daily bar "settled". Yahoo
# Finance and other providers can lag a few minutes behind 16:00 ET when
# splitting/dividend adjustments are processed; the buffer absorbs that
# without leaving the freshness layer flapping right at the close bell.
_DEFAULT_POST_CLOSE_BUFFER_MINUTES = 30


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


def nyse_close_at_et(day: date) -> datetime | None:
    """ET-aware datetime of NYSE's regular-session close on ``day``.

    Returns ``None`` when ``day`` is not a trading session (weekend,
    holiday). Early-close days (e.g. Black Friday's 13:00 ET close) are
    honoured — pandas_market_calendars carries the per-day market_close
    so this helper does not hard-code 16:00 ET.
    """
    schedule = _NYSE.schedule(start_date=day, end_date=day)
    if schedule.empty:
        return None
    market_close = schedule["market_close"].iloc[0]
    if not isinstance(market_close, pd.Timestamp):
        return None
    return market_close.tz_convert(_MARKET_TZ).to_pydatetime()


def is_post_close_et(*, buffer_minutes: int = _DEFAULT_POST_CLOSE_BUFFER_MINUTES) -> bool:
    """True iff today is a trading day and we are past close + buffer.

    Used by ``run_daily_update`` to decide whether the latest cached
    bar should be presumed final. Returns ``False`` on weekends and
    holidays — there is no close to be past.
    """
    close = nyse_close_at_et(today_et())
    if close is None:
        return False
    return now_et() >= close + timedelta(minutes=buffer_minutes)


def is_intraday_partial(
    *,
    row_date: date,
    row_updated_at: datetime,
    buffer_minutes: int = _DEFAULT_POST_CLOSE_BUFFER_MINUTES,
) -> bool:
    """Treat ``row`` as a not-yet-finalized intra-day bar.

    True iff ``row_date`` is today's session AND ``row_updated_at`` is
    strictly before today's close + buffer. Comparing in UTC keeps the
    callsite free of timezone bookkeeping — both inputs are converted
    if necessary.
    """
    if row_date != today_et():
        return False
    close = nyse_close_at_et(row_date)
    if close is None:
        return False
    cutoff = close + timedelta(minutes=buffer_minutes)
    # Normalize both sides to aware datetimes for the comparison.
    if row_updated_at.tzinfo is None:
        row_aware = row_updated_at.replace(tzinfo=ZoneInfo("UTC"))
    else:
        row_aware = row_updated_at
    return row_aware < cutoff


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

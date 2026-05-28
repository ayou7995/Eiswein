"""Catalyst calendar fetchers — earnings, macro releases, industry events.

Three independent feeders that the ``calendar_sync`` orchestrator unions
into a single upsert against the ``calendar_event`` table:

* :func:`fetch_earnings_for_symbols` — per-ticker quarterly earnings via
  yfinance ``Ticker.get_earnings_dates``. Bulk-friendly (one Ticker per
  symbol; yfinance throttling is mitigated by short request timeouts and
  per-symbol fault isolation — one bad symbol does not break the run).
* :func:`load_industry_events_from_yaml` — operator-curated YAML at the
  repo's ``docs/events.yaml``. Plain dict-loaded list, validated against
  a tight schema.
* :func:`generate_macro_release_schedule` — rule-based generator for
  recurring US macro releases (CPI, PCE, PPI, NFP, FOMC, PMI). FOMC
  dates are hard-coded per year because they are not algorithmically
  predictable (Fed publishes the calendar each Aug for next year).

These are pure / mostly-pure functions returning :class:`CalendarEventRow`
dicts ready for ``CalendarEventRepository.upsert_many`` — no DB or HTTP
side effects in this module itself.
"""

from __future__ import annotations

import asyncio
import calendar as stdlib_calendar
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import structlog
import yaml
import yfinance as yf

from app.db.repositories.calendar_event_repository import CalendarEventRow

logger = structlog.get_logger("eiswein.datasources.calendar")

# yfinance request envelope — per-symbol soft cap so a slow upstream
# doesn't stall the entire sync. Five seconds is generous for the
# earnings endpoint which returns ~10 rows.
_PER_SYMBOL_TIMEOUT_S = 5.0

# Earnings horizon — how far ahead to look for the next earnings call.
# yfinance returns up to a year out for most tickers; 180 days is the
# UI-relevant window for the catalyst chip and Earnings Date Proximity.
_EARNINGS_HORIZON_DAYS = 180


# --- Earnings (yfinance) ---------------------------------------------------


async def fetch_earnings_for_symbols(
    symbols: Sequence[str],
    *,
    as_of: date | None = None,
    horizon_days: int = _EARNINGS_HORIZON_DAYS,
) -> list[CalendarEventRow]:
    """Return upcoming earnings rows for ``symbols`` between today and
    today+``horizon_days``.

    Per-symbol fetch is fault-isolated: a network or parse failure on
    one symbol logs and produces zero rows for that symbol; other
    symbols continue. yfinance bulk has no API for earnings so this
    falls back to per-Ticker calls running in a thread pool.
    """
    if not symbols:
        return []
    cleaned = sorted({s.strip().upper() for s in symbols if s.strip()})
    cutoff_start = as_of or _today_utc()
    cutoff_end = cutoff_start + timedelta(days=horizon_days)

    # Per-symbol thread offload; gather concurrently. yfinance issues
    # individual HTTP calls so concurrency speeds up a 20-symbol
    # watchlist substantially without violating any throttle.
    coros = [
        asyncio.to_thread(
            _fetch_single_symbol_earnings,
            symbol,
            cutoff_start=cutoff_start,
            cutoff_end=cutoff_end,
        )
        for symbol in cleaned
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    rows: list[CalendarEventRow] = []
    for symbol, outcome in zip(cleaned, results, strict=True):
        if isinstance(outcome, Exception):
            logger.warning(
                "calendar_earnings_fetch_failed",
                symbol=symbol,
                error_type=type(outcome).__name__,
            )
            continue
        rows.extend(cast(list[CalendarEventRow], outcome))
    return rows


def _fetch_single_symbol_earnings(
    symbol: str,
    *,
    cutoff_start: date,
    cutoff_end: date,
) -> list[CalendarEventRow]:
    """Synchronous fetcher executed in a worker thread.

    Returns CalendarEventRow dicts for any earnings dates falling inside
    [cutoff_start, cutoff_end]. Empty list on no upcoming earnings.
    """
    ticker = yf.Ticker(symbol)
    try:
        frame = ticker.get_earnings_dates(limit=12)
    except Exception:
        # yfinance raises a grab-bag — wrap as empty result.
        raise
    if frame is None or frame.empty:
        return []

    rows: list[CalendarEventRow] = []
    for index_value, record in frame.iterrows():
        event_dt = _coerce_event_datetime(index_value)
        if event_dt is None:
            continue
        event_date = event_dt.date()
        if event_date < cutoff_start or event_date > cutoff_end:
            continue
        time_marker = _classify_earnings_time(event_dt)
        payload: dict[str, Any] = {}
        # EPS Estimate column (capitalisation varies across yfinance
        # versions); silent fallthrough if absent.
        for key in ("EPS Estimate", "epsEstimate", "eps_estimate"):
            if key in record.index:
                value = record[key]
                if value is not None and not _is_nan(value):
                    payload["consensus_eps"] = float(value)
                    break
        if time_marker:
            payload["time_marker"] = time_marker
        rows.append(
            CalendarEventRow(
                event_date=event_date,
                event_time=time_marker,
                type="earnings",
                ticker_symbol=symbol,
                title=f"{symbol} Earnings",
                payload_json=payload or None,
                source="yfinance",
            )
        )
    return rows


def _classify_earnings_time(dt: datetime) -> str | None:
    """Map an earnings datetime to BMO/AMC/None.

    yfinance returns the announce time embedded in the index when known
    (Eastern Time). Pre-market (< 09:30 ET) → BMO. Post-market
    (> 16:00 ET) → AMC. Mid-day usually means undisclosed time → None.
    """
    hour = dt.hour
    if hour < 9 or (hour == 9 and dt.minute < 30):
        return "BMO"
    if hour >= 16:
        return "AMC"
    return None


# --- Industry events (YAML) ------------------------------------------------


def load_industry_events_from_yaml(yaml_path: Path) -> list[CalendarEventRow]:
    """Parse ``events.yaml`` into CalendarEventRow dicts.

    Schema (per entry):
    ```
    - date: 2026-06-10
      title: NVDA GTC Day 1
      ticker: NVDA          # optional — omit for sector-wide events
      time: "9:00 PT"       # optional — display only
      tags: [Semis, AI]     # optional — informational, not used yet
    ```

    Missing file → empty list (no error). Malformed entry → logged and
    skipped (don't break the sync because one row in a hand-maintained
    file is wrong).
    """
    if not yaml_path.exists():
        return []
    try:
        with yaml_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        logger.warning(
            "calendar_industry_yaml_parse_failed",
            path=str(yaml_path),
            error=str(exc),
        )
        return []
    if not isinstance(raw, list):
        return []

    rows: list[CalendarEventRow] = []
    for index, entry in enumerate(raw):
        row = _parse_industry_entry(entry, ordinal=index)
        if row is not None:
            rows.append(row)
    return rows


def _parse_industry_entry(entry: Any, *, ordinal: int) -> CalendarEventRow | None:
    if not isinstance(entry, dict):
        logger.warning("calendar_industry_yaml_entry_not_dict", ordinal=ordinal)
        return None
    date_value = entry.get("date")
    title = entry.get("title")
    if not isinstance(title, str) or not title.strip():
        logger.warning("calendar_industry_yaml_missing_title", ordinal=ordinal)
        return None
    if isinstance(date_value, date):
        event_date = date_value
    elif isinstance(date_value, str):
        try:
            event_date = date.fromisoformat(date_value)
        except ValueError:
            logger.warning("calendar_industry_yaml_bad_date", ordinal=ordinal)
            return None
    else:
        logger.warning("calendar_industry_yaml_missing_date", ordinal=ordinal)
        return None

    ticker_raw = entry.get("ticker")
    ticker_symbol = ticker_raw.strip().upper() if isinstance(ticker_raw, str) else None
    time_value = entry.get("time")
    event_time = time_value if isinstance(time_value, str) else None
    tags_value = entry.get("tags")
    payload: dict[str, Any] = {}
    if isinstance(tags_value, list) and tags_value:
        payload["tags"] = [str(t) for t in tags_value]
    return CalendarEventRow(
        event_date=event_date,
        event_time=event_time,
        type="industry",
        ticker_symbol=ticker_symbol,
        title=title.strip(),
        payload_json=payload or None,
        source="yaml",
    )


# --- Macro releases (rule-based) -------------------------------------------

# Hard-coded FOMC scheduled meeting dates. Fed publishes one year ahead;
# operator updates this list each August. Entries past the supplied
# range are ignored. (2026 schedule per Fed press release 2025-09-17.)
_FOMC_MEETING_DATES: tuple[date, ...] = (
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
    date(2027, 1, 27),
    date(2027, 3, 17),
    date(2027, 4, 28),
)


def generate_macro_release_schedule(
    start: date,
    end: date,
) -> list[CalendarEventRow]:
    """Generate recurring US macro release events between ``start`` and
    ``end`` (inclusive).

    Rules — approximations sourced from BLS / BEA / ISM / FOMC release
    calendars:

    * CPI: ~10-15th of each month, 08:30 ET (BLS).
    * PCE / Core PCE: last business day of month, 08:30 ET (BEA).
    * PPI: mid-month (~12th), 08:30 ET (BLS).
    * NFP: first Friday of month, 08:30 ET (BLS).
    * ISM Manufacturing PMI: first business day of month, 10:00 ET.
    * FOMC: hard-coded scheduled meeting dates.

    These are best-effort. The actual day shifts year-to-year — the
    monthly approximations are close enough for a sidebar reminder
    ("CPI sometime around Wed-Thu") but the operator should cross-check
    BLS for the precise day during important release weeks.
    """
    if end < start:
        return []
    rows: list[CalendarEventRow] = []
    cursor_year = start.year
    cursor_month = start.month
    while True:
        month_start = date(cursor_year, cursor_month, 1)
        if month_start > end:
            break
        _, days_in_month = stdlib_calendar.monthrange(cursor_year, cursor_month)
        month_last = date(cursor_year, cursor_month, days_in_month)

        # CPI — second Tuesday-Friday window; use the 13th as the canonical
        # approximation. Bumps to next business day if landing on weekend.
        rows.extend(
            _maybe_release_row(
                _bump_to_business_day(date(cursor_year, cursor_month, 13)),
                start=start,
                end=end,
                title="CPI Release",
                event_time="8:30 ET",
            )
        )

        # PPI — typically a day after CPI, ~14th.
        rows.extend(
            _maybe_release_row(
                _bump_to_business_day(date(cursor_year, cursor_month, 14)),
                start=start,
                end=end,
                title="PPI Release",
                event_time="8:30 ET",
            )
        )

        # PCE — last business day of the month.
        rows.extend(
            _maybe_release_row(
                _last_business_day(month_last),
                start=start,
                end=end,
                title="PCE Release",
                event_time="8:30 ET",
            )
        )

        # NFP — first Friday of the month.
        rows.extend(
            _maybe_release_row(
                _first_weekday_of_month(month_start, weekday=stdlib_calendar.FRIDAY),
                start=start,
                end=end,
                title="Non-Farm Payrolls",
                event_time="8:30 ET",
            )
        )

        # ISM PMI — first business day of the month.
        rows.extend(
            _maybe_release_row(
                _bump_to_business_day(month_start),
                start=start,
                end=end,
                title="ISM Manufacturing PMI",
                event_time="10:00 ET",
            )
        )

        # Advance one month.
        if cursor_month == 12:
            cursor_year += 1
            cursor_month = 1
        else:
            cursor_month += 1

    # FOMC — explicit list intersection.
    for meeting_date in _FOMC_MEETING_DATES:
        if start <= meeting_date <= end:
            rows.append(
                CalendarEventRow(
                    event_date=meeting_date,
                    event_time="14:00 ET",
                    type="macro",
                    ticker_symbol=None,
                    title="FOMC Meeting",
                    payload_json={"note": "Statement + SEP if quarterly"},
                    source="hardcoded",
                )
            )
    return rows


def _maybe_release_row(
    event_date: date,
    *,
    start: date,
    end: date,
    title: str,
    event_time: str | None,
) -> Iterable[CalendarEventRow]:
    if event_date < start or event_date > end:
        return ()
    return (
        CalendarEventRow(
            event_date=event_date,
            event_time=event_time,
            type="macro",
            ticker_symbol=None,
            title=title,
            payload_json=None,
            source="hardcoded",
        ),
    )


def _first_weekday_of_month(month_start: date, *, weekday: int) -> date:
    """Earliest date in the month matching ISO weekday (0=Mon, 4=Fri)."""
    delta = (weekday - month_start.weekday()) % 7
    return month_start + timedelta(days=delta)


def _bump_to_business_day(target: date) -> date:
    """If ``target`` lands on a weekend, advance to the following Monday.

    Public holidays would also bump in a stricter implementation, but
    BLS already pre-publishes ad-hoc dates around major holidays — and
    the operator updates the FOMC list each year anyway. v1 accepts the
    weekend-only approximation.
    """
    weekday = target.weekday()
    if weekday == 5:  # Sat → Mon
        return target + timedelta(days=2)
    if weekday == 6:  # Sun → Mon
        return target + timedelta(days=1)
    return target


def _last_business_day(month_last: date) -> date:
    """Walk back from the last day of the month to the prior Mon-Fri."""
    cursor = month_last
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


# --- Misc helpers ----------------------------------------------------------


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _coerce_event_datetime(value: Any) -> datetime | None:
    """yfinance returns a ``pandas.Timestamp`` (tz-aware ET). Coerce to
    a plain ``datetime``; return None if unparseable."""
    try:
        if isinstance(value, datetime):
            return value
        return value.to_pydatetime()
    except Exception:
        return None


def _is_nan(value: Any) -> bool:
    try:
        return value != value  # NaN ≠ NaN
    except Exception:
        return False

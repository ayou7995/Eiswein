"""Catalyst calendar sync — daily orchestrator.

Pulls earnings, macro releases, and industry events from the three
:mod:`app.datasources.calendar_source` feeders and upserts into the
``calendar_event`` table. Idempotent — designed to be invoked from the
end of ``daily_update`` after price + indicators are persisted.

Failure isolation: each source runs in its own try/except so a yfinance
outage doesn't block the macro generator or YAML loader. Result is a
structured summary (counts per source + total upserted + orphans
purged) logged at INFO and returned for the caller to embed in the
daily_update audit row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.datasources.calendar_source import (
    fetch_earnings_for_symbols,
    generate_macro_release_schedule,
    load_industry_events_from_yaml,
)
from app.db.repositories.calendar_event_repository import (
    CalendarEventRepository,
    CalendarEventRow,
)

logger = structlog.get_logger("eiswein.ingestion.calendar_sync")

# Default forward window for macro generation. 180 days = ~6 months of
# CPI/PCE/NFP slots → enough to populate three months of the calendar
# UI in both directions even after the operator skips a sync day.
_MACRO_HORIZON_DAYS = 180
# How far back we still display past macro events on the calendar
# (grey-out). 60 days is enough for "last CPI was when?" lookups.
_MACRO_LOOKBACK_DAYS = 60


@dataclass(frozen=True)
class CalendarSyncResult:
    earnings_count: int
    macro_count: int
    industry_count: int
    orphans_deleted: int
    total_upserted: int


async def run_calendar_sync(
    session: Session,
    *,
    watchlist_symbols: Sequence[str],
    yaml_path: Path,
    as_of: date | None = None,
) -> CalendarSyncResult:
    """Execute one calendar sync against ``session``.

    Caller commits — this function flushes per repository write but
    leaves the outer transaction open so daily_update can roll up
    everything (prices + indicators + calendar) atomically.
    """
    today = as_of or datetime.now(UTC).date()
    repo = CalendarEventRepository(session)

    earnings_rows = await _safe_fetch_earnings(watchlist_symbols, today)
    macro_rows = _safe_generate_macro(today)
    industry_rows = _safe_load_industry(yaml_path)

    all_rows: list[CalendarEventRow] = [*earnings_rows, *macro_rows, *industry_rows]
    if all_rows:
        repo.upsert_many(all_rows)

    # Purge earnings + ticker-tied industry events for symbols that left
    # the watchlist. We compute the orphan set from the current calendar
    # table contents intersected against the current symbols set.
    orphans_deleted = _purge_orphans(repo, current_symbols=watchlist_symbols)

    result = CalendarSyncResult(
        earnings_count=len(earnings_rows),
        macro_count=len(macro_rows),
        industry_count=len(industry_rows),
        orphans_deleted=orphans_deleted,
        total_upserted=len(all_rows),
    )
    logger.info(
        "calendar_sync_complete",
        as_of=str(today),
        earnings=result.earnings_count,
        macro=result.macro_count,
        industry=result.industry_count,
        orphans_deleted=result.orphans_deleted,
        total=result.total_upserted,
    )
    return result


async def _safe_fetch_earnings(
    symbols: Sequence[str],
    today: date,
) -> list[CalendarEventRow]:
    try:
        return await fetch_earnings_for_symbols(symbols, as_of=today)
    except Exception as exc:
        logger.warning(
            "calendar_sync_earnings_source_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return []


def _safe_generate_macro(today: date) -> list[CalendarEventRow]:
    try:
        start = today - timedelta(days=_MACRO_LOOKBACK_DAYS)
        end = today + timedelta(days=_MACRO_HORIZON_DAYS)
        return generate_macro_release_schedule(start, end)
    except Exception as exc:
        logger.warning(
            "calendar_sync_macro_source_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return []


def _safe_load_industry(yaml_path: Path) -> list[CalendarEventRow]:
    try:
        return load_industry_events_from_yaml(yaml_path)
    except Exception as exc:
        logger.warning(
            "calendar_sync_industry_source_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return []


def _purge_orphans(
    repo: CalendarEventRepository,
    *,
    current_symbols: Sequence[str],
) -> int:
    """Remove ticker-tied events whose symbol no longer appears in the
    active watchlist. Macro events are unaffected.
    """
    # Pull existing ticker_symbols from the DB so we know what to
    # subtract. A focused query would be slightly faster, but the
    # calendar table is small (<1000 rows) so the full scan via the
    # repo is fine.
    from sqlalchemy import select  # repository import surface tight

    from app.db.models import CalendarEvent  # local import to keep

    stmt = (
        select(CalendarEvent.ticker_symbol)
        .where(CalendarEvent.ticker_symbol.is_not(None))
        .distinct()
    )
    stored_symbols = {
        row for row in repo._session.execute(stmt).scalars().all() if row
    }
    keep = {s.upper() for s in current_symbols if s and s.strip()}
    to_remove = stored_symbols - keep
    if not to_remove:
        return 0
    return repo.delete_orphans_for_symbols(to_remove)

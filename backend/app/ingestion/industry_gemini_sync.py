"""Weekly Gemini-backed industry catalyst sync.

Separate orchestrator from :mod:`calendar_sync` because the cadence is
different — calendar_sync runs daily (earnings + macro change daily-ish),
but conference dates are stable for weeks once announced, so calling
Gemini daily would waste API quota and add no value.

This module is the producer-side for the weekly scheduler job
``industry_sync`` AND the admin manual-trigger endpoint. Both call
:func:`run_industry_gemini_sync` with the same signature.

Side effects:
* Upserts rows into ``calendar_event``.
* Writes ``last_industry_sync_at`` to SystemMetadata so the UI can render
  "synced N hours ago" without re-deriving it from row contents.
* Increments a per-day ``gemini_requests_today`` counter and refuses to
  call if a safety budget is exceeded — guards against an accidental
  retry loop / runaway manual trigger eating into the free-tier daily
  request budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.datasources.gemini_industry_source import (
    fetch_upcoming_industry_events,
)
from app.db.repositories.calendar_event_repository import CalendarEventRepository
from app.db.repositories.system_metadata_repository import SystemMetadataRepository

logger = structlog.get_logger("eiswein.ingestion.industry_gemini_sync")

# Local safety net for daily request budget. Google AI Studio free tier
# is 1500 RPD; we'd normally hit 1 request/week. This 100 RPD ceiling
# stops a bug-induced retry storm from quietly burning quota for the
# rest of the day. Bump deliberately if a legitimate use case appears.
_LLM_USAGE_BUDGET_REQUESTS_PER_DAY: Final[int] = 100

# SystemMetadata keys (consolidated source of truth).
KEY_LAST_INDUSTRY_SYNC_AT: Final[str] = "last_industry_sync_at"
KEY_GEMINI_REQUESTS_BUDGET: Final[str] = "gemini_requests_budget"


@dataclass(frozen=True)
class IndustryGeminiSyncResult:
    """Audit shape for one run."""

    skipped_reason: str | None
    events_returned: int
    rows_upserted: int


async def run_industry_gemini_sync(
    session: Session,
    *,
    api_key: str,
    as_of: date | None = None,
) -> IndustryGeminiSyncResult:
    """Execute one Gemini-backed sync. Caller commits the session.

    Empty / missing key → returns ``skipped_reason='no_api_key'`` without
    making an HTTP call, mirroring the calendar_sync feeder behaviour."""
    today = as_of or datetime.now(UTC).date()
    metadata = SystemMetadataRepository(session)

    if not api_key:
        logger.info("industry_sync_skipped", reason="no_api_key")
        return IndustryGeminiSyncResult(
            skipped_reason="no_api_key", events_returned=0, rows_upserted=0
        )

    if _budget_exhausted(metadata, today=today):
        logger.warning(
            "industry_sync_skipped",
            reason="daily_budget_exhausted",
            budget=_LLM_USAGE_BUDGET_REQUESTS_PER_DAY,
        )
        return IndustryGeminiSyncResult(
            skipped_reason="daily_budget_exhausted",
            events_returned=0,
            rows_upserted=0,
        )

    _bump_budget_counter(metadata, today=today)

    rows = await fetch_upcoming_industry_events(api_key=api_key, as_of=today)
    upserted = 0
    if rows:
        repo = CalendarEventRepository(session)
        upserted = repo.upsert_many(rows)

    metadata.set_datetime(KEY_LAST_INDUSTRY_SYNC_AT, datetime.now(UTC))

    logger.info(
        "industry_sync_complete",
        as_of=str(today),
        events_returned=len(rows),
        rows_upserted=upserted,
    )
    return IndustryGeminiSyncResult(
        skipped_reason=None, events_returned=len(rows), rows_upserted=upserted
    )


def _budget_exhausted(metadata: SystemMetadataRepository, *, today: date) -> bool:
    """Read ``today_YYYY-MM-DD:count`` from the budget key; treat any
    parse error as "no usage recorded today" (worst case it lets one
    extra call through which is fine)."""
    raw = metadata.get(KEY_GEMINI_REQUESTS_BUDGET)
    if not raw:
        return False
    try:
        recorded_day, count_str = raw.split(":", 1)
        count = int(count_str)
    except ValueError:
        return False
    if recorded_day != today.isoformat():
        # Stale day — counter resets implicitly on next bump.
        return False
    return count >= _LLM_USAGE_BUDGET_REQUESTS_PER_DAY


def _bump_budget_counter(metadata: SystemMetadataRepository, *, today: date) -> None:
    raw = metadata.get(KEY_GEMINI_REQUESTS_BUDGET)
    count = 0
    if raw:
        try:
            recorded_day, count_str = raw.split(":", 1)
            if recorded_day == today.isoformat():
                count = int(count_str)
        except ValueError:
            count = 0
    metadata.set(KEY_GEMINI_REQUESTS_BUDGET, f"{today.isoformat()}:{count + 1}")


__all__ = [
    "KEY_GEMINI_REQUESTS_BUDGET",
    "KEY_LAST_INDUSTRY_SYNC_AT",
    "IndustryGeminiSyncResult",
    "run_industry_gemini_sync",
]

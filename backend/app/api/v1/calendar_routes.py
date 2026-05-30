"""Calendar API (Phase 7 — Catalyst Calendar v1).

Single read endpoint backing all four UI surfaces:

* `GET /api/v1/calendar/events?start=&end=&types[]=&tickers[]=`

The same shape powers the dedicated 行事曆 page (broad range, no
filters), the MarketOverview upcoming-macro banner (``types=macro``
+ 7-day window), the TickerDetail "next catalyst" chip
(``tickers=NVDA`` + forward window), and the catalyst-digest email
assembler (server-side use).

No write/sync endpoint — :func:`app.ingestion.calendar_sync.run_calendar_sync`
runs only as a side effect of ``run_daily_update`` so the upstream
yfinance / FRED calls follow the same rate-budget discipline as the
rest of the daily job.

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
slowapi + FastAPI inspect Pydantic models via forward references; the
``annotations`` future flag breaks resolution for ``response_model``.
Matches the other v1 routers.
"""

from datetime import date, datetime
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_calendar_event_repository,
    get_db_session,
    get_settings_dep,
)
from app.config import Settings
from app.db.repositories.calendar_event_repository import CalendarEventRepository
from app.db.repositories.system_metadata_repository import SystemMetadataRepository
from app.ingestion.industry_gemini_sync import (
    KEY_LAST_INDUSTRY_SYNC_AT,
    run_industry_gemini_sync,
)
from app.security.exceptions import ValidationError
from app.security.rate_limit import limiter

router = APIRouter(tags=["calendar"])
logger = structlog.get_logger("eiswein.api.calendar")

EventType = Literal["earnings", "macro", "industry"]

# Hard cap on the requested window so a malformed query (start=1900,
# end=today) can't dump 70k rows. 366 days covers the full v1 use cases
# (calendar page month nav + 6-month look-ahead chip).
_MAX_RANGE_DAYS = 366


# --- Pydantic wire models ------------------------------------------------


class CalendarEventOut(BaseModel):
    """Single calendar event projection.

    ``payload`` is a free-form dict because per-type metadata varies
    (earnings has ``time_marker`` + ``consensus_eps``; macro has
    ``note``; industry can carry tags). Frontend treats it as opaque
    payload and indexes by known keys when rendering.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    event_date: date
    event_time: str | None
    type: EventType
    ticker_symbol: str | None
    title: str
    payload: dict[str, object] | None
    source: str


class CalendarEventListResponse(BaseModel):
    data: list[CalendarEventOut]
    total: int
    range_start: date
    range_end: date


# --- Routes ---------------------------------------------------------------


@router.get(
    "/calendar/events",
    response_model=CalendarEventListResponse,
    summary="List calendar events in a date range",
)
@limiter.limit("60/minute")
async def list_calendar_events(
    request: Request,
    response: Response,
    start: Annotated[date, Query(description="Inclusive start (YYYY-MM-DD)")],
    end: Annotated[date, Query(description="Inclusive end (YYYY-MM-DD)")],
    types: Annotated[
        list[EventType] | None,
        Query(description="Filter to one or more event types"),
    ] = None,
    tickers: Annotated[
        list[str] | None,
        Query(
            description=(
                "Filter to specific tickers; macro events are always "
                "included regardless of this filter (a hidden CPI when "
                "the operator wanted 'just my EV tickers' is a UX trap)."
            ),
        ),
    ] = None,
    _user_id: int = Depends(current_user_id),
    repo: CalendarEventRepository = Depends(get_calendar_event_repository),
) -> CalendarEventListResponse:
    if end < start:
        raise ValidationError(
            message="end 必須晚於或等於 start",
            code="invalid_range",
            details={"start": str(start), "end": str(end)},
        )
    if (end - start).days > _MAX_RANGE_DAYS:
        raise ValidationError(
            message=f"區間超過 {_MAX_RANGE_DAYS} 天上限",
            code="range_too_wide",
            details={"max_days": _MAX_RANGE_DAYS},
        )
    rows = repo.list_in_range(
        start=start,
        end=end,
        types=types,
        ticker_symbols=tickers,
    )
    items = [
        CalendarEventOut(
            id=row.id,
            event_date=row.event_date,
            event_time=row.event_time,
            type=row.type,  # type: ignore[arg-type]  # checked by DB constraint
            ticker_symbol=row.ticker_symbol,
            title=row.title,
            payload=row.payload_json,
            source=row.source,
        )
        for row in rows
    ]
    return CalendarEventListResponse(
        data=items,
        total=len(items),
        range_start=start,
        range_end=end,
    )


# --- Industry Gemini sync — status + manual trigger ----------------------


class IndustrySyncStatusResponse(BaseModel):
    """Shape returned by ``GET /calendar/industry-sync/status``.

    Used by the Settings page to render a card with the last sync time
    + an enable/disable hint (rather than the operator having to grep
    server logs)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    last_sync_at: datetime | None
    stale_days_threshold: int


class IndustrySyncRunResponse(BaseModel):
    """Shape returned by ``POST /calendar/industry-sync/run``.

    The endpoint blocks until Gemini responds (typically 10-30 seconds);
    the response captures whether the sync ran or was skipped + counts."""

    model_config = ConfigDict(frozen=True)

    skipped_reason: str | None
    events_returned: int
    rows_upserted: int


@router.get(
    "/calendar/industry-sync/status",
    response_model=IndustrySyncStatusResponse,
    summary="Industry-event sync enablement + last-run timestamp",
)
@limiter.limit("60/minute")
async def get_industry_sync_status(
    request: Request,
    response: Response,
    _user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    session: Session = Depends(get_db_session),
) -> IndustrySyncStatusResponse:
    last_sync_at = SystemMetadataRepository(session).get_datetime(KEY_LAST_INDUSTRY_SYNC_AT)
    return IndustrySyncStatusResponse(
        enabled=settings.gemini_industry_sync_enabled,
        last_sync_at=last_sync_at,
        stale_days_threshold=settings.industry_sync_stale_days,
    )


@router.post(
    "/calendar/industry-sync/run",
    response_model=IndustrySyncRunResponse,
    summary="Manually trigger the Gemini-backed industry event sync",
)
# Lower rate limit than the read endpoint — manual sync is a serious
# operation (LLM call + DB write). 6/min keeps a clicked-too-fast user
# from melting through the daily quota guard.
@limiter.limit("6/minute")
async def run_industry_sync(
    request: Request,
    response: Response,
    _user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    session: Session = Depends(get_db_session),
) -> IndustrySyncRunResponse:
    api_key_secret = settings.gemini_api_key
    api_key = api_key_secret.get_secret_value() if api_key_secret else ""
    result = await run_industry_gemini_sync(session, api_key=api_key)
    session.commit()
    logger.info(
        "industry_sync_manual_run",
        skipped=result.skipped_reason,
        events=result.events_returned,
        rows=result.rows_upserted,
    )
    return IndustrySyncRunResponse(
        skipped_reason=result.skipped_reason,
        events_returned=result.events_returned,
        rows_upserted=result.rows_upserted,
    )

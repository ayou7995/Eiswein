"""Data source status + manual refresh + ticker status poll.

Endpoints:
* ``GET  /api/v1/data/status``            — DataSource health + ticker summary
* ``POST /api/v1/data/refresh``           — trigger ``run_daily_update`` (rate-limited)
* ``GET  /api/v1/ticker/{symbol}?only_status=1`` — lightweight poll for cold-start

Not using ``from __future__ import annotations`` here — slowapi's
limit decorator wraps the refresh handler, and FastAPI's forward-ref
resolution fails if the wrapper's ``__globals__`` differ from this
module's (same issue as auth_routes.py documented in Phase 0).
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_data_source_dep,
    get_db_session,
    get_settings_dep,
    get_watchlist_repository,
)
from app.api.v1.watchlist_routes import (
    WatchlistItem,
    validate_symbol_or_raise,
)
from app.config import Settings
from app.datasources.base import DataSource, DataSourceHealth
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.daily_ingestion import run_daily_update
from app.ingestion.market_calendar import is_trading_day_et, last_trading_day_et
from app.security.exceptions import NotFoundError
from app.security.rate_limit import limiter

router = APIRouter(tags=["data"])
logger = structlog.get_logger("eiswein.data")


class DataStatusSummary(BaseModel):
    pending: int
    ready: int
    failed: int
    delisted: int


class DataStatusResponse(BaseModel):
    provider: str
    provider_health: DataSourceHealth
    market_open_today: bool
    last_trading_day: str
    ticker_summary: DataStatusSummary


class RefreshResponse(BaseModel):
    ok: bool = True
    market_open: bool
    session_date: str
    symbols_requested: int
    symbols_succeeded: int
    symbols_failed: int
    symbols_delisted: int
    price_rows_upserted: int
    macro_rows_upserted: int


class TickerStatusResponse(BaseModel):
    symbol: str
    data_status: str
    last_refresh_at: datetime | None


@router.get(
    "/data/status",
    response_model=DataStatusResponse,
    summary="Data source health + watchlist data_status summary",
)
async def get_data_status(
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    data_source: DataSource = Depends(get_data_source_dep),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> DataStatusResponse:
    health = await data_source.health_check()
    rows = repo.list_for_user(user_id)
    summary = DataStatusSummary(
        pending=sum(1 for r in rows if r.data_status == "pending"),
        ready=sum(1 for r in rows if r.data_status == "ready"),
        failed=sum(1 for r in rows if r.data_status == "failed"),
        delisted=sum(1 for r in rows if r.data_status == "delisted"),
    )
    return DataStatusResponse(
        provider=settings.data_source_provider,
        provider_health=health,
        market_open_today=is_trading_day_et(),
        last_trading_day=last_trading_day_et().isoformat(),
        ticker_summary=summary,
    )


@router.post(
    "/data/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually trigger daily ingestion (rate-limited 1/hour)",
)
@limiter.limit("1/hour")
async def refresh_data(
    request: Request,
    _user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    data_source: DataSource = Depends(get_data_source_dep),
    session: Session = Depends(get_db_session),
) -> RefreshResponse:
    result = await run_daily_update(
        db=session, data_source=data_source, settings=settings
    )
    return RefreshResponse(
        ok=True,
        market_open=result.market_open,
        session_date=result.session_date.isoformat(),
        symbols_requested=result.symbols_requested,
        symbols_succeeded=result.symbols_succeeded,
        symbols_failed=result.symbols_failed,
        symbols_delisted=result.symbols_delisted,
        price_rows_upserted=result.price_rows_upserted,
        macro_rows_upserted=result.macro_rows_upserted,
    )


@router.get(
    "/ticker/{symbol}",
    response_model=TickerStatusResponse | WatchlistItem,
    summary="Lightweight status poll (only_status=1) or detail view",
)
def get_ticker(
    symbol: str,
    only_status: int = Query(default=0, ge=0, le=1),
    user_id: int = Depends(current_user_id),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> TickerStatusResponse | WatchlistItem:
    validated = validate_symbol_or_raise(symbol)
    row = repo.get(user_id=user_id, symbol=validated)
    if row is None:
        raise NotFoundError(details={"symbol": validated})
    if only_status == 1:
        return TickerStatusResponse(
            symbol=row.symbol,
            data_status=row.data_status,
            last_refresh_at=row.last_refresh_at,
        )
    return WatchlistItem.from_row(row)

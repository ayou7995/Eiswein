"""Ticker-scoped endpoints beyond the lightweight status poll.

* ``GET /api/v1/ticker/{symbol}/indicators`` returns the most recent
  stored :class:`DailySignal` rows for the symbol, keyed by indicator
  name. Does NOT recompute on demand — the daily_update job is the
  single producer of these rows.

Authentication is required (all routes under ``/api/v1`` except
``/health`` and ``/login`` require a valid access cookie).
"""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    current_user_id,
    get_daily_signal_repository,
    get_watchlist_repository,
)
from app.api.v1.watchlist_routes import validate_symbol_or_raise
from app.db.repositories.daily_signal_repository import DailySignalRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.indicators.base import INDICATOR_VERSION, SignalToneLiteral
from app.security.exceptions import NotFoundError

router = APIRouter(tags=["ticker"])


class IndicatorResultResponse(BaseModel):
    """API-facing shape of a single indicator result.

    Kept frozen so a mistaken mutation during serialization surfaces
    immediately (rule 11).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: float | None
    signal: SignalToneLiteral
    data_sufficient: bool
    short_label: str
    detail: dict[str, object]
    indicator_version: str


class TickerIndicatorsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    date: date
    timezone: str = "America/New_York"
    indicator_version: str
    indicators: dict[str, IndicatorResultResponse]


@router.get(
    "/ticker/{symbol}/indicators",
    response_model=TickerIndicatorsResponse,
    summary="Most recent computed indicators for a watchlist ticker",
)
def get_ticker_indicators(
    symbol: str,
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    repo: DailySignalRepository = Depends(get_daily_signal_repository),
) -> TickerIndicatorsResponse:
    validated = validate_symbol_or_raise(symbol)
    row = watchlist.get(user_id=user_id, symbol=validated)
    if row is None:
        raise NotFoundError(details={"symbol": validated})

    stored = repo.get_latest_for_symbol(validated)
    if not stored:
        # No computed indicators yet: return 404 so the frontend can
        # render a "computing..." state distinctly from "symbol not
        # on watchlist".
        raise NotFoundError(
            details={"symbol": validated, "reason": "no_signals_computed"},
        )

    latest_date = stored[0].date
    indicators = {
        r.indicator_name: IndicatorResultResponse(
            name=r.indicator_name,
            value=float(r.value) if r.value is not None else None,
            signal=_coerce_signal(r.signal),
            data_sufficient=r.data_sufficient,
            short_label=r.short_label,
            detail=dict(r.detail or {}),
            indicator_version=r.indicator_version,
        )
        for r in stored
    }

    return TickerIndicatorsResponse(
        symbol=validated,
        date=latest_date,
        indicator_version=INDICATOR_VERSION,
        indicators=indicators,
    )


def _coerce_signal(raw: str) -> SignalToneLiteral:
    if raw in ("green", "yellow", "red", "neutral"):
        return raw  # type: ignore[return-value]
    return "neutral"

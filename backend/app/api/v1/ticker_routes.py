"""Ticker-scoped endpoints beyond the lightweight status poll.

* ``GET /api/v1/ticker/{symbol}/indicators`` returns the most recent
  stored :class:`DailySignal` rows for the symbol, keyed by indicator
  name. Does NOT recompute on demand — the daily_update job is the
  single producer of these rows.
* ``GET /api/v1/ticker/{symbol}/signal`` returns the composed
  :class:`TickerSnapshot` (Action, TimingModifier, entry tiers,
  stop-loss, posture) plus the Pros/Cons list derived from the 8
  per-ticker indicator results.

Authentication is required (all routes under ``/api/v1`` except
``/health`` and ``/login`` require a valid access cookie).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import cast

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    current_user_id,
    get_daily_signal_repository,
    get_ticker_snapshot_repository,
    get_watchlist_repository,
)
from app.api.v1.watchlist_routes import validate_symbol_or_raise
from app.db.repositories.daily_signal_repository import DailySignalRepository
from app.db.repositories.ticker_snapshot_repository import TickerSnapshotRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.indicators.base import INDICATOR_VERSION, IndicatorResult, SignalToneLiteral
from app.security.exceptions import NotFoundError
from app.signals.labels import ACTION_LABELS, TIMING_BADGES
from app.signals.pros_cons import build_pros_cons_items
from app.signals.types import (
    ActionCategory,
    MarketPosture,
    ProsConsItem,
    TimingModifier,
)

router = APIRouter(tags=["ticker"])
logger = structlog.get_logger("eiswein.api.ticker")


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
            details={"symbol": validated, "reason": "indicators_unavailable"},
        )

    latest_date = stored[0].date
    indicators = {
        r.indicator_name: IndicatorResultResponse(
            name=r.indicator_name,
            value=float(r.value) if r.value is not None else None,
            signal=_coerce_signal(r.signal),
            data_sufficient=r.data_sufficient,
            short_label=r.short_label,
            detail=_safe_detail(dict(r.detail or {})),
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


_VALID_TONES: frozenset[SignalToneLiteral] = frozenset({"green", "yellow", "red", "neutral"})


def _coerce_signal(raw: str) -> SignalToneLiteral:
    if raw in _VALID_TONES:
        # cast documents intent without a blanket `type: ignore` — keeps
        # mypy strict-mode enforcement of the Literal contract at this
        # boundary (security audit HIGH finding).
        return cast(SignalToneLiteral, raw)
    # Unknown tone (schema drift between indicator versions, corrupted row,
    # or a future tone that hasn't reached this API layer yet). Log so the
    # drift is detectable; fall back to neutral to keep the response valid.
    logger.warning("unknown_signal_tone_coerced", raw=raw)
    return "neutral"


# --- Composed signal endpoint (Phase 3) -----------------------------------


class EntryTiersResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggressive: Decimal | None
    ideal: Decimal | None
    conservative: Decimal | None
    split_suggestion: tuple[int, int, int] = (30, 40, 30)


class ProsConsItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    tone: str
    short_label: str
    detail: dict[str, object]
    indicator_name: str


class ComposedSignalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    date: date
    timezone: str = "America/New_York"
    action: ActionCategory
    action_label: str
    direction_green_count: int
    direction_red_count: int
    timing_modifier: TimingModifier
    timing_badge: str | None
    show_timing_modifier: bool
    entry_tiers: EntryTiersResponse
    stop_loss: Decimal | None
    market_posture_at_compute: MarketPosture
    pros_cons: list[ProsConsItemResponse]
    indicator_version: str
    computed_at: datetime


@router.get(
    "/ticker/{symbol}/signal",
    response_model=ComposedSignalResponse,
    summary="Composed signal (action + timing + entry/stop) for a watchlist ticker",
)
def get_ticker_signal(
    symbol: str,
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    snapshot_repo: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    signals_repo: DailySignalRepository = Depends(get_daily_signal_repository),
) -> ComposedSignalResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    snapshot = snapshot_repo.get_latest_for_symbol(validated)
    if snapshot is None:
        raise NotFoundError(
            details={"symbol": validated, "reason": "signal_unavailable"},
        )

    action = _coerce_action(snapshot.action)
    timing = _coerce_timing(snapshot.timing_modifier)
    posture = _coerce_posture(snapshot.market_posture_at_compute)

    indicator_rows = signals_repo.get_latest_for_symbol(validated)
    results = {
        r.indicator_name: IndicatorResult(
            name=r.indicator_name,
            value=float(r.value) if r.value is not None else None,
            signal=_coerce_signal(r.signal),
            data_sufficient=r.data_sufficient,
            short_label=r.short_label,
            detail=dict(r.detail or {}),
            computed_at=r.computed_at,
            indicator_version=r.indicator_version,
        )
        for r in indicator_rows
    }
    pros_cons_items = build_pros_cons_items(results)

    # Timing badge is suppressed for exit-side actions (D1b). We honor
    # the stored ``show_timing_modifier`` rather than re-deriving it so
    # a historical row composed under different rules keeps its original
    # flag (audit-ability, A2-style).
    badge: str | None = TIMING_BADGES.get(timing) if snapshot.show_timing_modifier else None

    return ComposedSignalResponse(
        symbol=validated,
        date=snapshot.date,
        action=action,
        action_label=ACTION_LABELS[action],
        direction_green_count=snapshot.direction_green_count,
        direction_red_count=snapshot.direction_red_count,
        timing_modifier=timing,
        timing_badge=badge,
        show_timing_modifier=snapshot.show_timing_modifier,
        entry_tiers=EntryTiersResponse(
            aggressive=snapshot.entry_aggressive,
            ideal=snapshot.entry_ideal,
            conservative=snapshot.entry_conservative,
        ),
        stop_loss=snapshot.stop_loss,
        market_posture_at_compute=posture,
        pros_cons=[_to_wire_pros_cons(item) for item in pros_cons_items],
        indicator_version=snapshot.indicator_version,
        computed_at=snapshot.computed_at,
    )


def _coerce_action(raw: str) -> ActionCategory:
    try:
        return ActionCategory(raw)
    except ValueError:
        logger.warning("unknown_action_coerced", raw=raw)
        return ActionCategory.WATCH


def _coerce_timing(raw: str) -> TimingModifier:
    try:
        return TimingModifier(raw)
    except ValueError:
        logger.warning("unknown_timing_coerced", raw=raw)
        return TimingModifier.MIXED


def _coerce_posture(raw: str) -> MarketPosture:
    try:
        return MarketPosture(raw)
    except ValueError:
        logger.warning("unknown_posture_coerced", raw=raw)
        return MarketPosture.NORMAL


_SAFE_DETAIL_TYPES: tuple[type, ...] = (int, float, bool, str, type(None))


def _safe_detail(raw: dict[str, object]) -> dict[str, object]:
    """Drop any value that isn't a JSON primitive.

    Belt-and-suspenders against a future indicator placing a raw
    exception, DataFrame column name, or internal path into its detail
    dict. ``error_result`` already limits the failure case; this
    structural guard prevents regression when new indicators are added
    (security audit MEDIUM: pros-cons-detail-passthrough-no-allowlist).
    """
    return {k: v for k, v in raw.items() if isinstance(v, _SAFE_DETAIL_TYPES)}


def _to_wire_pros_cons(item: ProsConsItem) -> ProsConsItemResponse:
    return ProsConsItemResponse(
        category=item.category,
        tone=item.tone,
        short_label=item.short_label,
        detail=_safe_detail(dict(item.detail)),
        indicator_name=item.indicator_name,
    )

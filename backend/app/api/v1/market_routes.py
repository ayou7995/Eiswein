"""Market-scoped endpoints (Phase 3).

* ``GET /api/v1/market-posture`` — latest :class:`MarketSnapshot`,
  the current posture streak, and pros/cons items built from the
  4 regime indicators' most recent :class:`DailySignal` rows.

Authentication required (like every ``/api/v1`` route except
``/health`` and ``/login``). No user-filtering on the data itself:
per A1, market posture is global state shared across users.

Note: this module does NOT use ``from __future__ import annotations``
because Pydantic response-model resolution with slowapi's decorator
requires runtime annotations (Phase 1 lesson).
"""

from datetime import date, datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    current_user_id,
    get_daily_signal_repository,
    get_market_posture_streak_repository,
    get_market_snapshot_repository,
)
from app.db.repositories.daily_signal_repository import DailySignalRepository
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.db.repositories.market_snapshot_repository import MarketSnapshotRepository
from app.indicators.base import IndicatorResult, SignalToneLiteral
from app.security.exceptions import NotFoundError
from app.signals.labels import POSTURE_LABELS, posture_streak_badge
from app.signals.market_posture import REGIME_INDICATOR_NAMES
from app.signals.pros_cons import build_pros_cons_items
from app.signals.types import MarketPosture, ProsConsItem

_SPX_SYMBOL = "SPY"

router = APIRouter(tags=["market"])
logger = structlog.get_logger("eiswein.api.market")


class ProsConsItemResponse(BaseModel):
    """Wire shape for a single :class:`ProsConsItem`.

    ``detail`` intentionally typed as ``dict[str, object]`` so arbitrary
    indicator-specific numerics pass through — the frontend treats it
    as a dynamic structure for expand-on-tap.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    tone: str
    short_label: str
    detail: dict[str, object]
    indicator_name: str


class MarketPostureResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    timezone: str = "America/New_York"
    posture: MarketPosture
    posture_label: str
    regime_green_count: int
    regime_red_count: int
    regime_yellow_count: int
    streak_days: int
    streak_badge: str | None
    pros_cons: list[ProsConsItemResponse]
    indicator_version: str
    computed_at: datetime


@router.get(
    "/market-posture",
    response_model=MarketPostureResponse,
    summary="Current market posture + streak + regime pros/cons",
)
def get_market_posture(
    _user_id: int = Depends(current_user_id),
    snapshot_repo: MarketSnapshotRepository = Depends(get_market_snapshot_repository),
    streak_repo: MarketPostureStreakRepository = Depends(
        get_market_posture_streak_repository
    ),
    signals_repo: DailySignalRepository = Depends(get_daily_signal_repository),
) -> MarketPostureResponse:
    snapshot = snapshot_repo.get_latest()
    if snapshot is None:
        raise NotFoundError(details={"reason": "no_market_snapshot"})

    posture = _coerce_posture(snapshot.posture)
    streak = streak_repo.get_for_date(snapshot.date)
    # The streak row is written in the same transaction as the
    # snapshot; a missing streak means the job partially failed. We
    # fall back to a 1-day streak so the dashboard still renders.
    streak_days = streak.streak_days if streak is not None else 1

    regime_results = _load_regime_results(signals_repo, snapshot.date)
    pros_cons = build_pros_cons_items(regime_results)

    return MarketPostureResponse(
        date=snapshot.date,
        posture=posture,
        posture_label=POSTURE_LABELS[posture],
        regime_green_count=snapshot.regime_green_count,
        regime_red_count=snapshot.regime_red_count,
        regime_yellow_count=snapshot.regime_yellow_count,
        streak_days=streak_days,
        streak_badge=posture_streak_badge(posture, streak_days),
        pros_cons=[_to_wire(item) for item in pros_cons],
        indicator_version=snapshot.indicator_version,
        computed_at=snapshot.computed_at,
    )


def _coerce_posture(raw: str) -> MarketPosture:
    try:
        return MarketPosture(raw)
    except ValueError:
        logger.warning("unknown_market_posture_coerced", raw=raw)
        return MarketPosture.NORMAL


def _load_regime_results(
    signals_repo: DailySignalRepository, snapshot_date: date
) -> dict[str, IndicatorResult]:
    """Reconstruct IndicatorResult objects from DailySignal rows.

    Only the 4 regime indicator names are included — DailySignal holds
    all signals for the SPY "carrier" symbol on this date, including
    per-ticker direction/timing/macro indicators (if SPY is also on the
    watchlist), so we filter.
    """
    rows = signals_repo.get_latest_for_symbol(_SPX_SYMBOL)
    results: dict[str, IndicatorResult] = {}
    for row in rows:
        if row.date != snapshot_date:
            # Shouldn't happen (get_latest_for_symbol returns single
            # latest date) but we guard so drift is visible.
            continue
        if row.indicator_name not in REGIME_INDICATOR_NAMES:
            continue
        results[row.indicator_name] = IndicatorResult(
            name=row.indicator_name,
            value=float(row.value) if row.value is not None else None,
            signal=_coerce_signal(row.signal),
            data_sufficient=row.data_sufficient,
            short_label=row.short_label,
            detail=dict(row.detail or {}),
            computed_at=row.computed_at,
            indicator_version=row.indicator_version,
        )
    return results


def _coerce_signal(raw: str) -> SignalToneLiteral:
    if raw in ("green", "yellow", "red", "neutral"):
        return raw  # type: ignore[return-value]
    logger.warning("unknown_signal_tone_coerced", raw=raw)
    return "neutral"


def _to_wire(item: ProsConsItem) -> ProsConsItemResponse:
    return ProsConsItemResponse(
        category=item.category,
        tone=item.tone,
        short_label=item.short_label,
        detail=dict(item.detail),
        indicator_name=item.indicator_name,
    )

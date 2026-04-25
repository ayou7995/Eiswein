"""Ticker-scoped endpoints beyond the lightweight status poll.

* ``GET /api/v1/ticker/{symbol}/indicators`` returns the most recent
  stored :class:`DailySignal` rows for the symbol, keyed by indicator
  name. Does NOT recompute on demand — the daily_update job is the
  single producer of these rows.
* ``GET /api/v1/ticker/{symbol}/signal`` returns the composed
  :class:`TickerSnapshot` (Action, TimingModifier, entry tiers,
  stop-loss, posture) plus the Pros/Cons list derived from the 8
  per-ticker indicator results.
* ``GET /api/v1/ticker/{symbol}/prices`` returns DB-only OHLCV bars
  (ascending by date) for a bounded range selector. Used by the
  TickerDetail page to render TradingView Lightweight Charts. No
  network I/O — the daily_update job is the sole producer.

Authentication is required (all routes under ``/api/v1`` except
``/health`` and ``/login`` require a valid access cookie).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

import structlog
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    current_user_id,
    get_daily_price_repository,
    get_daily_signal_repository,
    get_ticker_snapshot_repository,
    get_watchlist_repository,
)
from app.api.v1._indicator_series import (
    RELATIVE_STRENGTH_MIN_BARS,
    SERIES_DAYS,
    SUPPORTED_INDICATORS,
    VOLUME_ANOMALY_MIN_BARS,
    build_bollinger_payload,
    build_close_frame,
    build_macd_payload,
    build_price_vs_ma_payload,
    build_relative_strength_payload,
    build_rsi_payload,
    build_volume_anomaly_payload,
)
from app.api.v1.watchlist_routes import validate_symbol_or_raise
from app.db.repositories.daily_price_repository import DailyPriceRepository
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


# --- Price history endpoint (Phase 4 chart feed) --------------------------

PriceRangeLiteral = Literal["1M", "3M", "6M", "1Y", "ALL"]

# ``ALL`` is capped server-side (TradingView perf + JSON payload budget).
# The cap lives here alongside the other range offsets so the policy is
# reviewable in one place.
_ALL_MAX_YEARS = 5

# (years, months) offsets per range. Months + years cover the selector;
# relativedelta() below does the leap-year-safe arithmetic at call
# time. Expressed as primitives here so the mypy-strict API package
# doesn't leak an `Any` (relativedelta has no typed stubs).
_RANGE_OFFSETS: dict[PriceRangeLiteral, tuple[int, int]] = {
    "1M": (0, 1),
    "3M": (0, 3),
    "6M": (0, 6),
    "1Y": (1, 0),
    "ALL": (_ALL_MAX_YEARS, 0),
}


class PriceBarResponse(BaseModel):
    """One OHLCV bar on the wire.

    Numeric fields are ``float`` — the DB stores ``Decimal`` for P&L
    precision (see :class:`DailyPrice` docstring) but the chart client
    consumes JSON numbers, and forcing a client to parse quoted Decimal
    strings for every bar on every ticker chart would be wasteful.
    """

    model_config = ConfigDict(frozen=True)

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    range: PriceRangeLiteral
    timezone: str = "America/New_York"
    bars: list[PriceBarResponse]


@router.get(
    "/ticker/{symbol}/prices",
    response_model=PriceHistoryResponse,
    summary="DB-only OHLCV history for a watchlist ticker",
)
def get_ticker_prices(
    symbol: str,
    # ``range_`` (trailing underscore) avoids shadowing the ``range``
    # builtin in module scope. FastAPI's ``alias`` keeps the wire name
    # ``?range=1M`` which is what the frontend spec calls for.
    range_: PriceRangeLiteral = Query(default="6M", alias="range"),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PriceHistoryResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    # Empty watchlist-member price history is a valid "computing" state
    # for the chart, distinct from "symbol not on watchlist". Return an
    # empty bars list rather than 404 so the frontend can show "資料處理中"
    # without treating it as a hard error.
    today = date.today()
    years, months = _RANGE_OFFSETS[range_]
    # relativedelta handles month-end + leap years (date.replace would
    # explode on 2024-02-29 → 2023-02-29). Leaves primitive types in
    # the annotated module so the strict-mypy API layer stays clean.
    start: date = today - relativedelta(years=years, months=months)
    rows = prices.get_range(validated, start=start, end=today)

    bars = [
        PriceBarResponse(
            date=r.date,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=int(r.volume),
        )
        for r in rows
    ]
    return PriceHistoryResponse(symbol=validated, range=range_, bars=bars)


# --- Per-indicator 60-day series endpoint ---------------------------------

# 200 trading days needed for MA200 + 60 trading days of output. We
# read by calendar-day window with generous slack (weekends, holidays)
# rather than counting trading days directly — the result is sliced to
# the trailing 60 rows so any extra padding is harmless.
_SERIES_LOOKBACK_DAYS = 400

# SPY is the canonical SPX proxy used across the regime indicators;
# the relative_strength branch reads its OHLCV from daily_price (always
# carried by the daily_update job, regardless of watchlist membership).
_SPX_PROXY_SYMBOL = "SPY"


class PriceVsMaPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    price: float | None
    ma50: float | None
    ma200: float | None


class PriceVsMaCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    price: float | None
    ma50: float | None
    ma200: float | None
    above_both_days: int


class PriceVsMaSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["price_vs_ma"]
    series: list[PriceVsMaPoint]
    summary_zh: str
    current: PriceVsMaCurrent


class RsiPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    daily: float | None
    weekly: float | None


class RsiCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    daily: float | None
    weekly: float | None
    zone: Literal["oversold", "neutral_weak", "neutral_strong", "overbought", "unknown"]


class RsiThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    oversold: int = 30
    overbought: int = 70


class RsiSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["rsi"]
    series: list[RsiPoint]
    summary_zh: str
    current: RsiCurrent
    thresholds: RsiThresholds


class MacdPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    macd: float | None
    signal: float | None
    histogram: float | None


class MacdCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    macd: float | None
    signal: float | None
    histogram: float | None
    last_cross: Literal["golden", "death"] | None
    bars_since_cross: int | None


class MacdSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["macd"]
    series: list[MacdPoint]
    summary_zh: str
    current: MacdCurrent


class BollingerPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    price: float | None
    upper: float | None
    middle: float | None
    lower: float | None


class BollingerCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    price: float | None
    upper: float | None
    middle: float | None
    lower: float | None
    position: float | None
    band_width: float | None
    band_width_5d_change: float | None


class BollingerSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["bollinger"]
    series: list[BollingerPoint]
    summary_zh: str
    current: BollingerCurrent


class VolumeAnomalyPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    volume: int
    price_change_pct: float | None
    avg_volume_20d: float | None


class VolumeAnomalyCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    today_volume: int
    avg_volume_20d: float | None
    ratio: float | None
    five_day_avg_ratio: float | None
    spike: bool


class VolumeAnomalySeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["volume_anomaly"]
    series: list[VolumeAnomalyPoint]
    summary_zh: str
    current: VolumeAnomalyCurrent


class RelativeStrengthPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    ticker_cum_return: float | None
    spx_cum_return: float | None
    diff: float | None


class RelativeStrengthCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker_20d_return: float | None
    spx_20d_return: float | None
    diff_20d: float | None
    ticker_60d_return: float | None
    spx_60d_return: float | None
    diff_60d: float | None


class RelativeStrengthSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    indicator: Literal["relative_strength"]
    series: list[RelativeStrengthPoint]
    summary_zh: str
    current: RelativeStrengthCurrent


IndicatorSeriesResponse = (
    PriceVsMaSeriesResponse
    | RsiSeriesResponse
    | MacdSeriesResponse
    | BollingerSeriesResponse
    | VolumeAnomalySeriesResponse
    | RelativeStrengthSeriesResponse
)


@router.get(
    "/ticker/{symbol}/indicator/{name}/series",
    response_model=IndicatorSeriesResponse,
    summary="60-day rolling series + zh-TW summary for a single ticker indicator",
)
def get_ticker_indicator_series(
    symbol: str,
    name: str,
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> IndicatorSeriesResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    if name not in SUPPORTED_INDICATORS:
        raise NotFoundError(
            details={"symbol": validated, "indicator": name, "reason": "unknown_indicator"},
        )

    end = date.today()
    start = end - timedelta(days=_SERIES_LOOKBACK_DAYS)
    rows = prices.get_range(validated, start=start, end=end)
    frame = build_close_frame(rows)

    if frame.empty or len(frame) < SERIES_DAYS:
        # Distinct from "ticker not on watchlist" — the chart UI uses
        # this 404 to render "資料處理中" rather than a hard error.
        raise NotFoundError(
            details={
                "symbol": validated,
                "indicator": name,
                "reason": "insufficient_history",
            },
        )

    if name == "price_vs_ma":
        return PriceVsMaSeriesResponse.model_validate(build_price_vs_ma_payload(validated, frame))
    if name == "rsi":
        return RsiSeriesResponse.model_validate(build_rsi_payload(validated, frame))
    if name == "macd":
        return MacdSeriesResponse.model_validate(build_macd_payload(validated, frame))
    if name == "bollinger":
        return BollingerSeriesResponse.model_validate(build_bollinger_payload(validated, frame))
    if name == "volume_anomaly":
        # Needs the prior-20-day rolling baseline + the 60-day output
        # window — total 80 bars. Distinct from the global 60-bar
        # pre-flight so the route can return a precise 404 when the
        # warm-up isn't satisfied.
        if len(frame) < VOLUME_ANOMALY_MIN_BARS:
            raise NotFoundError(
                details={
                    "symbol": validated,
                    "indicator": name,
                    "reason": "insufficient_history",
                },
            )
        return VolumeAnomalySeriesResponse.model_validate(
            build_volume_anomaly_payload(validated, frame)
        )
    # relative_strength: SUPPORTED_INDICATORS already gates this branch.
    # Loads SPY independently — SPY does not need to be on the user's
    # watchlist, only present in daily_price (the daily_update job
    # always carries SPY for the regime indicators).
    spy_rows = prices.get_range(_SPX_PROXY_SYMBOL, start=start, end=end)
    spy_frame = build_close_frame(spy_rows)
    if len(frame) < RELATIVE_STRENGTH_MIN_BARS or len(spy_frame) < RELATIVE_STRENGTH_MIN_BARS:
        raise NotFoundError(
            details={
                "symbol": validated,
                "indicator": name,
                "reason": "insufficient_history",
            },
        )
    return RelativeStrengthSeriesResponse.model_validate(
        build_relative_strength_payload(validated, frame, spy_frame)
    )

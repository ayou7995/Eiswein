"""Market-scoped endpoints (Phase 3).

* ``GET /api/v1/market-posture`` — latest :class:`MarketSnapshot`,
  the current posture streak, and pros/cons items built from the
  4 regime indicators' most recent :class:`DailySignal` rows.
* ``GET /api/v1/market/indicator/{name}/series`` — 60-day rolling
  series + zh-TW summary for the 6 supported market-regime / macro
  indicators (``spx_ma``, ``vix``, ``yield_spread``, ``ad_day``,
  ``dxy``, ``fed_rate``). All math lives in :mod:`_market_series`;
  this module owns DB I/O and dispatch only.

Authentication required (like every ``/api/v1`` route except
``/health`` and ``/login``). No user-filtering on the data itself:
per A1, market posture is global state shared across users.

Note: this module does NOT use ``from __future__ import annotations``
because Pydantic response-model resolution with slowapi's decorator
requires runtime annotations (Phase 1 lesson).
"""

from datetime import date, datetime, timedelta
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    current_user_id,
    get_daily_price_repository,
    get_daily_signal_repository,
    get_macro_repository,
    get_market_posture_streak_repository,
    get_market_snapshot_repository,
)
from app.api.v1._market_series import (
    DXY_MACRO_SERIES,
    DXY_MIN_BARS,
    FED_FUNDS_MACRO_SERIES,
    HYG_IEF_MIN_BARS,
    RSP_SPY_MIN_BARS,
    SERIES_DAYS,
    SKEW_MIN_BARS,
    SPX_ADX_MIN_BARS,
    SUPPORTED_MARKET_INDICATORS,
    UNRATE_MIN_MONTHS,
    VIX_TERM_MIN_BARS,
    build_ad_day_payload,
    build_dxy_payload,
    build_fed_rate_payload,
    build_hyg_ief_payload,
    build_macro_value_series,
    build_rsp_spy_payload,
    build_skew_payload,
    build_spx_adx_payload,
    build_spx_ma_payload,
    build_spy_frame,
    build_unrate_payload,
    build_vix_payload,
    build_vix_term_payload,
    build_yield_spread_payload,
)
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.daily_signal_repository import DailySignalRepository
from app.db.repositories.macro_repository import MacroRepository
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
_SPX_MA_MIN_BARS = 200
_AD_DAY_MIN_BARS = SERIES_DAYS + 1
# Lookback wide enough to cover a 2-year (~504 trading-day) display window
# plus 200 bars of MA200 warm-up. Repository returns whatever's actually
# in the DB so this is just an upper bound on the SQL range query.
_SPY_LOOKBACK_DAYS = 1100


def _spy_lookback_for(window: int) -> int:
    """Calendar-day lookback that covers ``window`` trading days plus MA200
    warm-up. Trading→calendar uses 365/252; we add a 200-bar cushion for
    MA200, then floor at the original 1100-day budget so the 1M/3M/1Y
    fast paths still hit the same SQL range as before."""
    needed = int(window * 365 / 252) + _SPX_MA_MIN_BARS
    return max(_SPY_LOOKBACK_DAYS, needed)


# Display-window options exposed via ``?days=N``. Each indicator falls
# back to its own default when the caller omits the param. Validation
# clamps to [_DAYS_MIN, _DAYS_MAX] so callers can't ask for absurd
# windows.
_DAYS_MIN = 21
_DAYS_MAX = 1260

# ``?range=all`` walks back this many trading days — the deepest
# backfill the bootstrap wizard offers. 1260 ~= 5 years * 252 sessions/yr.
_ALL_RANGE_DAYS = 1260
_DEFAULT_DAYS: dict[str, int] = {
    "spx_ma": SERIES_DAYS,
    "vix": SERIES_DAYS,
    "ad_day": SERIES_DAYS,
    "yield_spread": 252,
    "dxy": SERIES_DAYS,
    "fed_rate": 365,
    "spx_adx": SERIES_DAYS,
    "vix_term": SERIES_DAYS,
    "rsp_spy": SERIES_DAYS,
    "hyg_ief": SERIES_DAYS,
    # Phase 5: short-term tail-risk + long-term macro additions.
    "skew": SERIES_DAYS,
    # UNRATE is monthly; default to 5 years of calendar history for the
    # chart so the Sahm Rule trend over a cycle is legible.
    "unrate": 365 * 5,
}

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
    timeframe: str
    # v2 (2026-06): actual underlying-data date. < snapshot date when
    # FRED / yfinance / breadth lagged; UI shows a staleness pill.
    data_as_of: date | None = None


class MarketPostureResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    timezone: str = "America/New_York"
    # Mid-term posture (weeks horizon, 6 regime indicators).
    posture: MarketPosture
    posture_label: str
    regime_green_count: int
    regime_red_count: int
    regime_yellow_count: int
    streak_days: int
    streak_badge: str | None
    # Short-term posture (days horizon, 4 regime indicators: vix +
    # ad_day + vix_term + skew). UI renders this beside the mid-term
    # posture so the operator can distinguish "structurally fine but
    # today is panicky" from "structurally weakening".
    posture_short: MarketPosture
    posture_short_label: str
    regime_short_green_count: int
    regime_short_red_count: int
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
    streak_repo: MarketPostureStreakRepository = Depends(get_market_posture_streak_repository),
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

    posture_short = _coerce_posture(snapshot.posture_short)
    return MarketPostureResponse(
        date=snapshot.date,
        posture=posture,
        posture_label=POSTURE_LABELS[posture],
        regime_green_count=snapshot.regime_green_count,
        regime_red_count=snapshot.regime_red_count,
        regime_yellow_count=snapshot.regime_yellow_count,
        streak_days=streak_days,
        streak_badge=posture_streak_badge(posture, streak_days),
        posture_short=posture_short,
        posture_short_label=POSTURE_LABELS[posture_short],
        regime_short_green_count=snapshot.regime_short_green_count,
        regime_short_red_count=snapshot.regime_short_red_count,
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

    Includes the 4 voting regime indicators plus ``spx_adx`` — ADX is
    a context modifier rather than a vote (per the v2 Phase 2 spec) but
    it needs to surface in the MarketOverview pros_cons list under the
    MID timeframe so the UI can render its card alongside ``spx_ma``.
    Voting still happens against ``REGIME_INDICATOR_NAMES`` upstream.
    """
    display_names = REGIME_INDICATOR_NAMES | {
        "spx_adx",
        "vix_term",
        "rsp_spy",
        "hyg_ief",
    }
    rows = signals_repo.get_latest_for_symbol(_SPX_SYMBOL)
    results: dict[str, IndicatorResult] = {}
    for row in rows:
        if row.date != snapshot_date:
            # Shouldn't happen (get_latest_for_symbol returns single
            # latest date) but we guard so drift is visible.
            continue
        if row.indicator_name not in display_names:
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
            data_as_of=row.data_as_of,
        )
    return results


_VALID_TONES: frozenset[SignalToneLiteral] = frozenset({"green", "yellow", "red", "neutral"})


def _coerce_signal(raw: str) -> SignalToneLiteral:
    if raw in _VALID_TONES:
        # cast documents intent without a blanket `type: ignore` — keeps
        # mypy strict-mode enforcement of the Literal contract at this
        # boundary (security audit HIGH finding).
        return cast(SignalToneLiteral, raw)
    logger.warning("unknown_signal_tone_coerced", raw=raw)
    return "neutral"


_SAFE_DETAIL_TYPES: tuple[type, ...] = (int, float, bool, str, type(None))


def _safe_detail(raw: dict[str, object]) -> dict[str, object]:
    """Drop any non-JSON-primitive value from indicator detail dicts.

    Belt-and-suspenders against a future indicator leaking internal
    state (security audit MEDIUM: pros-cons-detail-passthrough).
    """
    return {k: v for k, v in raw.items() if isinstance(v, _SAFE_DETAIL_TYPES)}


def _to_wire(item: ProsConsItem) -> ProsConsItemResponse:
    return ProsConsItemResponse(
        category=item.category,
        tone=item.tone,
        short_label=item.short_label,
        detail=_safe_detail(dict(item.detail)),
        indicator_name=item.indicator_name,
        timeframe=item.timeframe,
        data_as_of=item.data_as_of,
    )


# --- Per-indicator 60-day market-series endpoint --------------------------


class SpxMaPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    price: float | None
    ma50: float | None
    ma200: float | None


class SpxMaCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    price: float | None
    ma50: float | None
    ma200: float | None
    above_both_days: int


class SpxMaSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["spx_ma"]
    series: list[SpxMaPoint]
    summary_zh: str
    current: SpxMaCurrent


class VixPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    level: float | None


class VixCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: float | None
    ten_day_change: float | None
    trend: Literal["rising", "falling", "flat", "unknown"]
    zone: Literal["low", "normal", "elevated", "panic"]
    percentile_1y: float | None


class VixThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    low: int
    normal_high: int
    elevated_high: int


class VixSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["vix"]
    series: list[VixPoint]
    summary_zh: str
    current: VixCurrent
    thresholds: VixThresholds


class YieldSpreadPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    spread: float | None
    ten_year: float | None
    two_year: float | None


class YieldSpreadCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    spread: float | None
    ten_year: float | None
    two_year: float | None
    days_since_inversion: int | None
    last_inversion_end: str | None


class YieldSpreadSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["yield_spread"]
    series: list[YieldSpreadPoint]
    summary_zh: str
    current: YieldSpreadCurrent


class AdDayPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    classification: Literal["accum", "distrib", "neutral"]
    spx_change: float | None
    volume_ratio: float | None
    # OHLCV per day — drives the candle-classification chart. Optional so
    # pre-feature snapshots without these fields don't break the route.
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


class AdDayCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    accum_count_25d: int
    distrib_count_25d: int
    net_25d: int
    accum_count_5d: int
    distrib_count_5d: int
    net_5d: int


class AdDaySeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["ad_day"]
    series: list[AdDayPoint]
    summary_zh: str
    current: AdDayCurrent


class DxyPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    level: float | None
    ma20: float | None


class DxyCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: float | None
    ma20: float | None
    streak_rising: bool
    streak_falling: bool
    streak_days: int
    ma20_change_5d: float | None


class DxySeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["dxy"]
    series: list[DxyPoint]
    summary_zh: str
    current: DxyCurrent


class FedRatePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    rate: float | None


class FedRateCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_rate: float | None
    prior_30d_rate: float | None
    delta_30d: float | None
    days_since_last_change: int | None
    last_change_date: str | None
    last_change_direction: Literal["hike", "cut"] | None


class FedRateSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator: Literal["fed_rate"]
    series: list[FedRatePoint]
    summary_zh: str
    current: FedRateCurrent


class SpxAdxPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    adx: float | None
    plus_di: float | None
    minus_di: float | None


class SpxAdxCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    adx: float | None
    plus_di: float | None
    minus_di: float | None
    zone: Literal["choppy", "ambiguous", "trending", "unknown"]
    direction: Literal["up", "down", "unknown"]


class SpxAdxThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    no_trend: float
    trend: float


class SpxAdxSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["spx_adx"]
    series: list[SpxAdxPoint]
    summary_zh: str
    current: SpxAdxCurrent
    thresholds: SpxAdxThresholds


class VixTermPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    vix: float | None
    vix3m: float | None
    ratio: float | None


class VixTermCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    vix: float | None
    vix3m: float | None
    ratio: float | None
    zone: Literal["contango", "flat", "inverted", "unknown"]


class VixTermThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    contango: float
    inversion: float


class VixTermSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["vix_term"]
    series: list[VixTermPoint]
    summary_zh: str
    current: VixTermCurrent
    thresholds: VixTermThresholds


class RspSpyPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    rsp: float | None
    spy: float | None
    ratio: float | None


class RspSpyCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    rsp: float | None
    spy: float | None
    ratio: float | None
    slope_20d_pct: float | None


class RspSpySeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["rsp_spy"]
    series: list[RspSpyPoint]
    summary_zh: str
    current: RspSpyCurrent


class HygIefPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    hyg: float | None
    ief: float | None
    ratio: float | None


class HygIefCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    hyg: float | None
    ief: float | None
    ratio: float | None
    slope_20d_pct: float | None


class HygIefSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["hyg_ief"]
    series: list[HygIefPoint]
    summary_zh: str
    current: HygIefCurrent


class SkewPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    level: float | None


class SkewCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: float | None
    ten_day_change: float | None
    zone: Literal["normal", "elevated", "high", "unknown"]
    percentile_1y: float | None


class SkewThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    normal_high: float
    elevated_high: float


class SkewSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["skew"]
    series: list[SkewPoint]
    summary_zh: str
    current: SkewCurrent
    thresholds: SkewThresholds


class UnratePoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    rate: float | None
    sahm_value: float | None


class UnrateCurrent(BaseModel):
    model_config = ConfigDict(frozen=True)
    current_rate: float | None
    three_month_avg: float | None
    twelve_month_low: float | None
    sahm_value: float | None
    sahm_distance_to_trigger: float | None
    zone: Literal["healthy", "warning", "recession", "unknown"]


class UnrateThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    warning: float
    trigger: float


class UnrateSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicator: Literal["unrate"]
    series: list[UnratePoint]
    summary_zh: str
    current: UnrateCurrent
    thresholds: UnrateThresholds


MarketIndicatorSeriesResponse = (
    SpxMaSeriesResponse
    | VixSeriesResponse
    | YieldSpreadSeriesResponse
    | AdDaySeriesResponse
    | DxySeriesResponse
    | FedRateSeriesResponse
    | SpxAdxSeriesResponse
    | VixTermSeriesResponse
    | RspSpySeriesResponse
    | HygIefSeriesResponse
    | SkewSeriesResponse
    | UnrateSeriesResponse
)


def _insufficient(name: str) -> NotFoundError:
    return NotFoundError(
        details={"name": name, "reason": "insufficient_history"},
    )


@router.get(
    "/market/indicator/{name}/series",
    response_model=MarketIndicatorSeriesResponse,
    summary="Rolling series + zh-TW summary for a single market indicator",
)
def get_market_indicator_series(
    name: str,
    days: int | None = Query(
        default=None,
        ge=_DAYS_MIN,
        le=_DAYS_MAX,
        description=(
            "Trailing-window length. For most indicators this counts trading"
            " days; for fed_rate it counts calendar days (FRED forward-fills"
            " weekends into the output). Falls back to a per-indicator default"
            " when omitted (yield_spread=252, fed_rate=365, others=60)."
        ),
    ),
    range_: Literal["all"] | None = Query(
        default=None,
        alias="range",
        description=(
            "When set to 'all', bypasses the ``days`` cap and returns up to"
            " 10 years of history — useful for the chart 'ALL' selector when"
            " the operator backfilled more than 5 years."
        ),
    ),
    _user_id: int = Depends(current_user_id),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
    macro: MacroRepository = Depends(get_macro_repository),
) -> MarketIndicatorSeriesResponse:
    if name not in SUPPORTED_MARKET_INDICATORS:
        raise NotFoundError(
            details={"reason": "unknown_indicator", "name": name},
        )

    window = (
        _ALL_RANGE_DAYS if range_ == "all" else (days if days is not None else _DEFAULT_DAYS[name])
    )

    if name == "spx_ma":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        rows = prices.get_range(_SPX_SYMBOL, start=start, end=end)
        frame = build_spy_frame(rows)
        if frame.empty or len(frame) < _SPX_MA_MIN_BARS:
            raise _insufficient(name)
        return SpxMaSeriesResponse.model_validate(build_spx_ma_payload(frame, window))

    if name == "ad_day":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        rows = prices.get_range(_SPX_SYMBOL, start=start, end=end)
        frame = build_spy_frame(rows)
        if frame.empty or len(frame) < _AD_DAY_MIN_BARS:
            raise _insufficient(name)
        return AdDaySeriesResponse.model_validate(build_ad_day_payload(frame, window))

    if name == "vix":
        vix_series = build_macro_value_series(macro.get_all_for_series("VIXCLS"))
        if vix_series.empty or len(vix_series.dropna()) < SERIES_DAYS:
            raise _insufficient(name)
        return VixSeriesResponse.model_validate(build_vix_payload(vix_series, window))

    if name == "yield_spread":
        ten_series = build_macro_value_series(macro.get_all_for_series("DGS10"))
        two_series = build_macro_value_series(macro.get_all_for_series("DGS2"))
        if (
            ten_series.empty
            or two_series.empty
            or len(ten_series.dropna()) < SERIES_DAYS
            or len(two_series.dropna()) < SERIES_DAYS
        ):
            raise _insufficient(name)
        return YieldSpreadSeriesResponse.model_validate(
            build_yield_spread_payload(ten_series, two_series, window)
        )

    if name == "dxy":
        dxy_series = build_macro_value_series(macro.get_all_for_series(DXY_MACRO_SERIES))
        if dxy_series.empty or len(dxy_series.dropna()) < DXY_MIN_BARS:
            raise _insufficient(name)
        return DxySeriesResponse.model_validate(build_dxy_payload(dxy_series, window))

    if name == "spx_adx":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        rows = prices.get_range(_SPX_SYMBOL, start=start, end=end)
        frame = build_spy_frame(rows)
        if frame.empty or len(frame) < SPX_ADX_MIN_BARS:
            raise _insufficient(name)
        return SpxAdxSeriesResponse.model_validate(build_spx_adx_payload(frame, window))

    if name == "vix_term":
        vix_series = build_macro_value_series(macro.get_all_for_series("VIXCLS"))
        vix3m_series = build_macro_value_series(macro.get_all_for_series("VXVCLS"))
        if (
            vix_series.empty
            or vix3m_series.empty
            or len(vix_series.dropna()) < VIX_TERM_MIN_BARS
            or len(vix3m_series.dropna()) < VIX_TERM_MIN_BARS
        ):
            raise _insufficient(name)
        return VixTermSeriesResponse.model_validate(
            build_vix_term_payload(vix_series, vix3m_series, window)
        )

    if name == "rsp_spy":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        rsp_rows = prices.get_range("RSP", start=start, end=end)
        spy_rows = prices.get_range(_SPX_SYMBOL, start=start, end=end)
        rsp_frame = build_spy_frame(rsp_rows)
        spy_frame = build_spy_frame(spy_rows)
        if (
            rsp_frame.empty
            or spy_frame.empty
            or len(rsp_frame) < RSP_SPY_MIN_BARS
            or len(spy_frame) < RSP_SPY_MIN_BARS
        ):
            raise _insufficient(name)
        return RspSpySeriesResponse.model_validate(
            build_rsp_spy_payload(rsp_frame, spy_frame, window)
        )

    if name == "hyg_ief":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        hyg_rows = prices.get_range("HYG", start=start, end=end)
        ief_rows = prices.get_range("IEF", start=start, end=end)
        hyg_frame = build_spy_frame(hyg_rows)
        ief_frame = build_spy_frame(ief_rows)
        if (
            hyg_frame.empty
            or ief_frame.empty
            or len(hyg_frame) < HYG_IEF_MIN_BARS
            or len(ief_frame) < HYG_IEF_MIN_BARS
        ):
            raise _insufficient(name)
        return HygIefSeriesResponse.model_validate(
            build_hyg_ief_payload(hyg_frame, ief_frame, window)
        )

    if name == "skew":
        end = date.today()
        start = end - timedelta(days=_spy_lookback_for(window))
        rows = prices.get_range("^SKEW", start=start, end=end)
        frame = build_spy_frame(rows)
        if frame.empty or len(frame) < SKEW_MIN_BARS:
            raise _insufficient(name)
        return SkewSeriesResponse.model_validate(build_skew_payload(frame, window))

    if name == "unrate":
        unrate_series = build_macro_value_series(macro.get_all_for_series("UNRATE"))
        if unrate_series.empty or len(unrate_series.dropna()) < UNRATE_MIN_MONTHS:
            raise _insufficient(name)
        return UnrateSeriesResponse.model_validate(
            build_unrate_payload(unrate_series, window)
        )

    # fed_rate: SUPPORTED_MARKET_INDICATORS already gates this branch.
    fed_series = build_macro_value_series(macro.get_all_for_series(FED_FUNDS_MACRO_SERIES))
    if fed_series.empty or len(fed_series.dropna()) < 1:
        raise _insufficient(name)
    return FedRateSeriesResponse.model_validate(build_fed_rate_payload(fed_series, window))

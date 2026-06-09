"""SPX ADX — market-regime trend strength.

Per-ticker ADX is great for one stock; for the market as a whole the
same formula on SPY's OHLCV tells the operator whether the indices are
trending or chopping. SPX ADX is an INDEPENDENT mid-term market-regime
indicator — read alongside SPX 50/200 MA (which gives direction) rather
than as a modifier on other regime cards. Operator interpretation:
SPX ADX ≥ 25 + SPX above 200 MA = trending up with conviction; SPX
ADX < 20 = drifting regardless of direction.

Signal table matches the per-ticker one (see ``timing/adx.py``); SPX
ADX never gets a RED because direction isn't its job. We pass through
the same +DI/-DI lines via ``detail`` so the UI can show "Tech tape
trending up with strength" vs "Tech tape weakly drifting".

This indicator reuses the per-ticker ``wilder_adx`` math; the only
thing it adds is "use SPY as the price frame" by reading
``context.spx_frame``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of, last_float, wilder_adx
from app.indicators.base import IndicatorResult, insufficient_result
from app.indicators.timing.adx import (
    _NO_TREND_THRESHOLD,
    _SLOPE_LOOKBACK,
    _STRONG_TREND_THRESHOLD,
    _TREND_THRESHOLD,
    _adx_slope,
    _classify,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "spx_adx"
_LENGTH = 14
_MIN_BARS = _LENGTH * 2 + 5


def compute_spx_adx(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    """Compute ADX on SPY OHLCV from ``context.spx_frame``.

    ``frame`` is ignored — the orchestrator passes the SPX frame in
    too but for completeness we read ``context.spx_frame`` directly so
    the call shape matches other market_regime indicators that lean on
    the context."""
    _ = frame
    spx = context.spx_frame
    if spx is None or spx.empty:
        return insufficient_result(NAME)
    required = {"high", "low", "close"}
    if not required.issubset(spx.columns):
        return insufficient_result(NAME)
    data_as_of = frame_as_of(spx)
    if len(spx) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars": len(spx)}, data_as_of=data_as_of
        )

    result = wilder_adx(spx["high"], spx["low"], spx["close"], length=_LENGTH)
    adx_value = last_float(result.adx)
    plus_di = last_float(result.plus_di)
    minus_di = last_float(result.minus_di)
    if adx_value is None or plus_di is None or minus_di is None:
        return insufficient_result(NAME, data_as_of=data_as_of)

    slope = _adx_slope(result.adx, _SLOPE_LOOKBACK)
    direction = "up" if plus_di > minus_di else "down"
    signal, short_label = _classify(adx_value, slope, name_prefix="SPX ADX")

    return IndicatorResult(
        name=NAME,
        value=adx_value,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "adx": adx_value,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "direction": direction,
            "slope_5d": slope,
            "no_trend_threshold": _NO_TREND_THRESHOLD,
            "trend_threshold": _TREND_THRESHOLD,
            "strong_trend_threshold": _STRONG_TREND_THRESHOLD,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )

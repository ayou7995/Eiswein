"""RSP/SPY ratio — equal-weight vs cap-weight breadth (mid-term).

Compares SPX equal-weight (RSP, every member 0.2 %) to cap-weight (SPY,
Mag-7 ≈ 30 %). The ratio tells you whether the typical stock is keeping
up with the cap-weighted index:

* Rising ratio (RSP outperforming SPY) → **broad participation**. The
  average stock is up; rally isn't being carried by a handful of
  mega-caps.
* Falling ratio (SPY outperforming RSP) → **narrow rally / Mag-7
  carrying**. Indices may be at highs while the median S&P member is
  flat or down — historically a late-cycle warning.

This indicator is DISPLAY-ONLY in the mid-term regime card — it does
not vote in posture. The reason: it's highly correlated with spx_ma
(when SPX is in uptrend, RSP usually is too), so adding it to the vote
would double-count direction. Where it earns its keep is in the
"narrow rally" scenario — SPX at highs with a falling ratio is a
visual flag, not a posture verdict.

20-day slope as a percentage of the ratio is the signal — same
threshold semantics as the HYG/IEF credit spread indicator so the two
read consistently when read side-by-side.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd

from app.indicators._helpers import frame_as_of
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "rsp_spy"

_LOOKBACK = 20
_MIN_BARS = _LOOKBACK + 5
# ±0.05 % per day = ±1 % over 20 trading days; deliberately matches the
# HYG/IEF threshold so the two cross-asset cards have consistent
# "what counts as a real move" semantics.
_SLOPE_GREEN_PCT_PER_DAY = 0.05
_SLOPE_RED_PCT_PER_DAY = -0.05


def compute_rsp_spy(_frame: object, context: IndicatorContext) -> IndicatorResult:
    spy = context.spx_frame
    rsp = context.rsp_frame
    if spy is None or spy.empty or "close" not in spy.columns:
        return insufficient_result(NAME)
    if rsp is None or rsp.empty or "close" not in rsp.columns:
        return insufficient_result(NAME)

    data_as_of = _min_date(frame_as_of(spy), frame_as_of(rsp))

    if len(spy) < _MIN_BARS or len(rsp) < _MIN_BARS:
        return insufficient_result(
            NAME,
            detail={"bars_spy": len(spy), "bars_rsp": len(rsp)},
            data_as_of=data_as_of,
        )

    joined = pd.concat(
        [spy["close"].rename("spy"), rsp["close"].rename("rsp")], axis=1
    ).dropna()
    if len(joined) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars_joined": len(joined)}, data_as_of=data_as_of
        )

    ratio = joined["rsp"] / joined["spy"]
    current_ratio = float(ratio.iloc[-1])
    tail = ratio.iloc[-_LOOKBACK:]
    slope_pct_per_day = _percent_slope_per_day(tail)
    slope_20d_pct = slope_pct_per_day * _LOOKBACK

    signal, short_label = _classify(
        slope_pct_per_day=slope_pct_per_day, slope_20d_pct=slope_20d_pct
    )

    return IndicatorResult(
        name=NAME,
        value=current_ratio,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "ratio": current_ratio,
            "rsp_close": float(joined["rsp"].iloc[-1]),
            "spy_close": float(joined["spy"].iloc[-1]),
            "slope_pct_per_day": slope_pct_per_day,
            "slope_20d_pct": slope_20d_pct,
            "lookback_days": _LOOKBACK,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _percent_slope_per_day(series: pd.Series) -> float:
    """Linear slope of ``series`` expressed as percent of the FIRST value
    per day. Same magnitude semantics as the existing ADX slope helper —
    "where did we drift to from where we started", normalised so the
    threshold is meaningful across regimes."""
    if len(series) < 2:
        return 0.0
    first = float(series.iloc[0])
    last = float(series.iloc[-1])
    if first == 0:
        return 0.0
    total_pct = (last - first) / first * 100.0
    return total_pct / len(series)


def _classify(
    *, slope_pct_per_day: float, slope_20d_pct: float
) -> tuple[SignalToneLiteral, str]:
    suffix = f"RSP/SPY 20D {slope_20d_pct:+.2f}%"
    if slope_pct_per_day >= _SLOPE_GREEN_PCT_PER_DAY:
        return SignalTone.GREEN, f"{suffix}（廣度健康）"
    if slope_pct_per_day <= _SLOPE_RED_PCT_PER_DAY:
        return SignalTone.RED, f"{suffix}（窄漲警示）"
    return SignalTone.YELLOW, f"{suffix}（廣度持平）"


def _min_date(a: date | None, b: date | None) -> date | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


__all__ = ["NAME", "compute_rsp_spy"]

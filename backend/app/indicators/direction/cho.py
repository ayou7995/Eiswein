"""Chaikin Oscillator (CHO) — accumulation / distribution momentum.

Marc Chaikin's 1980s indicator. Sits on top of the Accumulation /
Distribution Line (A/D Line), which weights each bar's volume by where
close fell within the day's range:

    money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
    money_flow_volume     = money_flow_multiplier * volume
    AD                    = cumsum(money_flow_volume)

The Chaikin Oscillator is then ``EMA(AD, 3) - EMA(AD, 10)`` — a
MACD-of-AD-line that smooths out the noise and highlights regime
transitions in big-player buying / selling.

How we read it (mid-term direction vote — 2-4 week horizon):

* CHO > 0 + last bar > prior bar  → GREEN (accumulation accelerating)
* CHO < 0 + last bar < prior bar  → RED   (distribution accelerating)
* CHO near zero / flipping        → YELLOW

We do NOT vote on the absolute magnitude — only sign + slope — because
CHO is unbounded and the magnitude depends on volume scale (different
between AAPL and a small-cap). Sign-and-slope is the canonical Chaikin
read and matches Sherry's "big players accumulating" lens (see
``docs/SHERRY_SYSTEM.md`` Article 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
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

NAME = "cho"

_FAST = 3
_SLOW = 10
_MIN_BARS = _SLOW + 5
_FLAT_THRESHOLD_PCT = 0.05  # within 5% of the zero line counts as "near zero"


def compute_cho(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty:
        return insufficient_result(NAME)
    required = {"high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return insufficient_result(NAME)
    data_as_of = frame_as_of(frame)
    if len(frame) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars": len(frame)}, data_as_of=data_as_of
        )

    high = frame["high"].astype("float64")
    low = frame["low"].astype("float64")
    close = frame["close"].astype("float64")
    volume = frame["volume"].astype("float64")

    cho_series = _chaikin_oscillator(high, low, close, volume, fast=_FAST, slow=_SLOW)
    cho_value = float(cho_series.iloc[-1]) if not pd.isna(cho_series.iloc[-1]) else None
    if cho_value is None:
        return insufficient_result(NAME, data_as_of=data_as_of)

    cleaned = cho_series.dropna()
    prior_value = float(cleaned.iloc[-2]) if len(cleaned) >= 2 else cho_value
    slope_5d = _slope(cho_series, lookback=5)
    # Volume scale baseline — gives us a magnitude-agnostic "near-zero"
    # threshold so KO at 50M vol / day and AAPL at 80M vol / day map onto
    # the same yellow band when CHO is hovering.
    volume_scale = float(volume.rolling(20, min_periods=1).mean().iloc[-1])
    flat_threshold = volume_scale * _FLAT_THRESHOLD_PCT

    signal, short_label = _classify(
        cho=cho_value,
        prior=prior_value,
        slope=slope_5d,
        flat_threshold=flat_threshold,
    )

    return IndicatorResult(
        name=NAME,
        value=cho_value,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "cho": cho_value,
            "prior": prior_value,
            "slope_5d": slope_5d,
            "flat_threshold": flat_threshold,
            "volume_scale": volume_scale,
            "fast": _FAST,
            "slow": _SLOW,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _chaikin_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    *,
    fast: int,
    slow: int,
) -> pd.Series:
    """Standard CHO = EMA(AD, fast) - EMA(AD, slow)."""
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfm = mfm.fillna(0.0)
    money_flow_volume = mfm * volume
    ad_line = money_flow_volume.cumsum()
    return ad_line.ewm(span=fast, adjust=False).mean() - ad_line.ewm(
        span=slow, adjust=False
    ).mean()


def _slope(series: pd.Series, *, lookback: int) -> float | None:
    cleaned = series.dropna()
    if len(cleaned) <= lookback:
        return None
    return float((cleaned.iloc[-1] - cleaned.iloc[-1 - lookback]) / lookback)


def _classify(
    *,
    cho: float,
    prior: float,
    slope: float | None,
    flat_threshold: float,
) -> tuple[SignalToneLiteral, str]:
    """Map (cho, slope) → (tone, short_label).

    GREEN  — positive AND accelerating (above prior bar)
    RED    — negative AND accelerating downward (below prior bar)
    YELLOW — sign-flip, near-zero hover, or decelerating in either direction
    """
    near_zero = abs(cho) < flat_threshold
    rising = cho > prior
    falling = cho < prior
    cho_label = _format_magnitude(cho)

    if near_zero:
        return SignalTone.YELLOW, f"CHO 接近零線 ({cho_label})"
    if cho > 0 and rising:
        return SignalTone.GREEN, f"買盤加速 (CHO {cho_label} ↑)"
    if cho < 0 and falling:
        return SignalTone.RED, f"賣盤加速 (CHO {cho_label} ↓)"
    # Positive but slowing OR negative but slowing — momentum dissipating.
    arrow = "↓" if slope is not None and slope < 0 else "↑"
    side = "買盤" if cho > 0 else "賣盤"
    return SignalTone.YELLOW, f"{side}減速 (CHO {cho_label} {arrow})"


def _format_magnitude(value: float) -> str:
    """Format a large signed number with k/M/B suffix.

    CHO is volume-weighted so raw values can hit tens of millions for
    actively-traded tickers. Showing "-1.2e+07" or "-11849513" both flunk
    the "operator should be able to read at a glance" test. A suffix
    keeps the magnitude scannable without losing the sign / order.
    """
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"{value / 1e9:+.2f}B"
    if abs_v >= 1e6:
        return f"{value / 1e6:+.2f}M"
    if abs_v >= 1e3:
        return f"{value / 1e3:+.2f}k"
    return f"{value:+.2f}"


__all__ = ["NAME", "compute_cho"]

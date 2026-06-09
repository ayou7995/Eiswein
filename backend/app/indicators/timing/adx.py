"""ADX (14) — trend STRENGTH (not direction) gauge.

ADX answers a different question from MACD / RSI / Bollinger: not
"which way is the market going?", but "how strongly is it going there
at all?". It's an INDEPENDENT mid-term indicator — read alongside the
other indicator cards rather than as a modifier on them. The earlier
v2 plan sketched a "context modifier" role where weak ADX would mute
other badges visually; that design was dropped in favour of letting
the operator read each card on its own merits.

Reading the bands:

* ``ADX < 20``  → choppy / sideways. Common interpretation: mean-reversion
  setups (RSI 30/70, Bollinger touches) tend to work better than
  trend-follow signals here. But that's *operator judgement*, not an
  algorithmic gate — ADX itself just labels the regime.
* ``20 ≤ ADX < 25``  → emerging trend, ambiguous.
* ``25 ≤ ADX < 40``  → strong trend in play.
* ``ADX ≥ 40`` → very strong trend, often late stages.

Wilder's framing: ADX never tells you direction. To get direction
you look at ``+DI vs -DI`` (which side is on top). We surface those
via ``detail`` so the UI can render the full diagnostic, but the
signal tone is driven purely by the strength reading.

Signal table:
* ADX ≥ 25 + ADX rising over the last 5 bars       → GREEN  (trend confirmed)
* ADX ≥ 25 + ADX falling over the last 5 bars      → YELLOW (trend weakening)
* ADX < 20                                          → YELLOW (no trend)
* 20 ≤ ADX < 25                                     → YELLOW (emerging, wait)

(There is no "RED" — ADX is a strength gauge, not a directional bet.
Use ±DI for direction.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of, last_float, wilder_adx
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "adx"
_LENGTH = 14
# 2x length to fully warm up the recursive smoothing; below this the
# ADX line hasn't stabilised and we return data_sufficient=False.
_MIN_BARS = _LENGTH * 2 + 5
_SLOPE_LOOKBACK = 5

_NO_TREND_THRESHOLD = 20.0
_TREND_THRESHOLD = 25.0
_STRONG_TREND_THRESHOLD = 40.0


def compute_adx(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty:
        return insufficient_result(NAME)
    required = {"high", "low", "close"}
    if not required.issubset(frame.columns):
        return insufficient_result(NAME)
    data_as_of = frame_as_of(frame)
    if len(frame) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars": len(frame)}, data_as_of=data_as_of
        )

    result = wilder_adx(frame["high"], frame["low"], frame["close"], length=_LENGTH)
    adx_value = last_float(result.adx)
    plus_di = last_float(result.plus_di)
    minus_di = last_float(result.minus_di)
    if adx_value is None or plus_di is None or minus_di is None:
        return insufficient_result(NAME, data_as_of=data_as_of)

    slope = _adx_slope(result.adx, _SLOPE_LOOKBACK)
    direction = "up" if plus_di > minus_di else "down"
    signal, short_label = _classify(adx_value, slope)

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


def _adx_slope(adx: pd.Series, lookback: int) -> float | None:
    """Slope of the ADX line over the last ``lookback`` bars.

    Positive = trend strengthening, negative = trend weakening. Slope is
    just the simple difference (latest minus N bars ago) divided by N
    — same shape as the RSI trend hint elsewhere in this package."""
    cleaned = adx.dropna()
    if len(cleaned) <= lookback:
        return None
    return float((cleaned.iloc[-1] - cleaned.iloc[-1 - lookback]) / lookback)


def _classify(
    adx: float, slope: float | None, *, name_prefix: str = "ADX"
) -> tuple[SignalToneLiteral, str]:
    """Return (signal, short_label) per the table in the module docstring.

    ADX ≥ 25 with a stable-or-rising slope is GREEN (strong trend in
    play). A meaningfully falling slope while ADX is still ≥ 25 means
    the trend is dissipating — YELLOW. The slope deadband is -0.5 per
    bar so noise-level fluctuation in the smoothing doesn't flip us
    every refresh.

    ``name_prefix`` lets the SPX ADX indicator label its output as
    ``"SPX ADX ..."`` while per-ticker stays ``"ADX ..."`` — the rest of
    the format is identical so the dashboard renders them in the same
    "[name] [value]（[zone]）" shape.
    """
    weakening_threshold = -0.5
    if adx >= _TREND_THRESHOLD:
        if slope is not None and slope < weakening_threshold:
            return SignalTone.YELLOW, f"{name_prefix} {adx:.0f}（強趨勢 ↓）"
        return SignalTone.GREEN, f"{name_prefix} {adx:.0f}（強趨勢）"
    if adx >= _NO_TREND_THRESHOLD:
        return SignalTone.YELLOW, f"{name_prefix} {adx:.0f}（趨勢未明朗）"
    return SignalTone.YELLOW, f"{name_prefix} {adx:.0f}（盤整）"

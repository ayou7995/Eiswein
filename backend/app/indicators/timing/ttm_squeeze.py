"""TTM Squeeze (John Carter) — volatility-coil + breakout-direction gauge.

A pure-pandas implementation of John Carter's 2007 indicator. The
squeeze is read as a two-stage state machine:

1. **Squeeze ON** — Bollinger Bands (20, 2σ) are wholly contained inside
   Keltner Channels (20-EMA ± 1.5 × ATR20). Markets compress before they
   expand; this is the loading phase. Signal: YELLOW (等待點火).

2. **Squeeze FIRES** — BBs cross *outside* Keltner Channels after a
   period of compression. Direction comes from the momentum histogram:
   linear-regression slope of ``close - midpoint`` where
   ``midpoint = (max(high20) + min(low20) + SMA20(close)) / 3``.

   * fires + momentum > 0  → GREEN (向上點火)
   * fires + momentum < 0  → RED   (向下點火)

3. **No squeeze / post-fire** — neither YELLOW nor a fresh fire. Signal:
   YELLOW (中性) with ``squeeze_on=False``; the UI just shows the
   momentum histogram colour for context.

We require the squeeze to have been ON within the last ``_FIRE_WINDOW``
bars to count a "fire" — without that, a stock that's just been trending
quietly would mis-trigger as a fire whenever volatility ticks up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

from app.indicators._helpers import (
    bollinger_bands,
    frame_as_of,
    keltner_channels,
    linreg_slope,
    sma,
)
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "ttm_squeeze"

_LENGTH = 20
_BB_STD_MULT = 2.0
_KC_ATR_MULT = 1.5
_FIRE_WINDOW = 5
_MIN_BARS = _LENGTH * 2 + _FIRE_WINDOW


def compute_ttm_squeeze(
    frame: pd.DataFrame, context: IndicatorContext
) -> IndicatorResult:
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

    high = frame["high"].astype("float64")
    low = frame["low"].astype("float64")
    close = frame["close"].astype("float64")

    bb = bollinger_bands(close, length=_LENGTH, std_mult=_BB_STD_MULT)
    kc = keltner_channels(high, low, close, length=_LENGTH, atr_mult=_KC_ATR_MULT)

    squeeze = (bb.upper < kc.upper) & (bb.lower > kc.lower)
    momentum_raw = _ttm_momentum(high, low, close, length=_LENGTH)
    # Normalise momentum to "% of close" so LAC at $4.53 and META at $500
    # produce comparable magnitudes — without this the LAC momentum reads
    # 0.03 while META reads 3.0 for the exact same signal strength.
    momentum_pct = (momentum_raw / close) * 100.0

    squeeze_on = bool(squeeze.iloc[-1])
    fired_up, fired_down = _fire_state(squeeze, momentum_pct)
    last_momentum = float(momentum_pct.iloc[-1]) if not pd.isna(momentum_pct.iloc[-1]) else 0.0
    last_close = float(close.iloc[-1])

    signal, short_label = _classify(
        squeeze_on=squeeze_on,
        fired_up=fired_up,
        fired_down=fired_down,
        momentum=last_momentum,
    )

    return IndicatorResult(
        name=NAME,
        value=last_momentum,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "squeeze_on": squeeze_on,
            "fired_up": fired_up,
            "fired_down": fired_down,
            "momentum": last_momentum,
            "momentum_rising": _momentum_rising(momentum_pct),
            "bb_upper": float(bb.upper.iloc[-1]),
            "bb_lower": float(bb.lower.iloc[-1]),
            "kc_upper": float(kc.upper.iloc[-1]),
            "kc_lower": float(kc.lower.iloc[-1]),
            "close": last_close,
            "length": _LENGTH,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _ttm_momentum(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    length: int,
) -> pd.Series:
    """John Carter's momentum oscillator.

    Subtracts a rolling midpoint from close, then runs a length-period
    linear-regression slope. Positive slope = price riding above the
    midpoint and accelerating; negative = the opposite. We return the
    slope directly (not the LR endpoint) so the magnitude is comparable
    across tickers regardless of price scale.
    """
    highest = high.rolling(length, min_periods=length).max()
    lowest = low.rolling(length, min_periods=length).min()
    sma20 = sma(close, length)
    midpoint = (highest + lowest + sma20) / 3.0
    delta = close - midpoint
    return linreg_slope(delta, length=length)


def _fire_state(squeeze: pd.Series, momentum: pd.Series) -> tuple[bool, bool]:
    """Did the squeeze just release in the last ``_FIRE_WINDOW`` bars?

    A "fire" is a transition from True → False in the squeeze series.
    Direction comes from the sign of momentum at the fire bar. Returns
    ``(fired_up, fired_down)`` — at most one can be True.
    """
    window = squeeze.iloc[-_FIRE_WINDOW - 1 :].astype(bool)
    if len(window) < 2:
        return False, False
    prev = window.shift(1, fill_value=False)
    transitions = prev & (~window)
    fire_bars = transitions[transitions].index
    if len(fire_bars) == 0:
        return False, False
    last_fire = fire_bars[-1]
    fire_momentum = momentum.loc[last_fire]
    if pd.isna(fire_momentum):
        return False, False
    if fire_momentum > 0:
        return True, False
    return False, True


def _momentum_rising(momentum: pd.Series) -> bool:
    """True iff the last two momentum readings are increasing."""
    cleaned = momentum.dropna()
    if len(cleaned) < 2:
        return False
    return bool(cleaned.iloc[-1] > cleaned.iloc[-2])


def _classify(
    *,
    squeeze_on: bool,
    fired_up: bool,
    fired_down: bool,
    momentum: float,
) -> tuple[SignalToneLiteral, str]:
    """Translate the squeeze state machine to (tone, short_label).

    Vote-side rules (短期 5-vote table in ``direction_short``):

    * GREEN if a fresh up-fire is in play (loaded → released → momentum > 0)
    * RED   on a fresh down-fire (released → momentum < 0)
    * YELLOW while the squeeze is currently ON (loaded but not yet released)
    * YELLOW otherwise (no compression / no recent fire — UI shows
      momentum colour for context but the vote stays neutral)
    """
    prefix = f"Squeeze 動能 {momentum:+.2f}%"
    if fired_up:
        return SignalTone.GREEN, f"{prefix}（向上點火）"
    if fired_down:
        return SignalTone.RED, f"{prefix}（向下點火）"
    if squeeze_on:
        return SignalTone.YELLOW, f"{prefix}（醞釀中 · 等待點火）"
    direction = "正" if momentum >= 0 else "負"
    return SignalTone.YELLOW, f"{prefix}（無壓縮 · 動能{direction}）"


__all__ = ["NAME", "compute_ttm_squeeze"]

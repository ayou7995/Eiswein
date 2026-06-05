"""Dynamic stop-loss calculator (I16).

Rules (v2 Phase 2 — 2026-06):

* When an ATR value is available (from the ATR indicator): the
  preferred stop is ``close - 2 * ATR``. ATR adapts per-stock so a
  volatile ticker (TSLA) gets a wider stop than a stable one (KO)
  for the same logical "give it room to breathe" goal.
* Otherwise, fall back to the legacy MA/BB rules:
    * Healthy trend (action ∈ {STRONG_BUY, BUY, HOLD}): ``200MA × 0.97``
    * Weakening trend (action ∈ {WATCH, REDUCE, EXIT}):
      ``Bollinger-lower × 0.97`` with last-resort 5-day low fallback.

Returns ``None`` when data is insufficient for the branch chosen —
caller persists ``NULL`` and the UI shows "─".

The 0.97 multiplier bakes in a 3% buffer beneath the reference MA so a
one-day wick doesn't trigger an exit (Sherry-style trailing stop). The
2.0 ATR multiplier is the academic-consensus middle of the 1.5-3.0
range used by trend-following systems — tight enough to cap loss,
wide enough to survive normal pullbacks.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from app.indicators._helpers import bollinger_bands, last_float, sma
from app.signals.types import ActionCategory

if TYPE_CHECKING:
    import pandas as pd

_BUFFER: Final[float] = 0.97
_DEFAULT_ATR_MULTIPLIER: Final[float] = 2.0
_QUANTIZER: Final[Decimal] = Decimal("0.0001")
_HEALTHY_ACTIONS: Final[frozenset[ActionCategory]] = frozenset(
    {ActionCategory.STRONG_BUY, ActionCategory.BUY, ActionCategory.HOLD}
)


def compute_stop_loss(
    ticker_frame: pd.DataFrame,
    *,
    direction_action: ActionCategory,
    atr_value: float | None = None,
    atr_multiplier: float = _DEFAULT_ATR_MULTIPLIER,
) -> Decimal | None:
    """Compute the stop-loss price for the ticker given the D1a action.

    When ``atr_value`` is passed (the ATR indicator computed a number),
    we use ``last_close - atr_multiplier * atr_value`` — adapts the
    stop distance to the ticker's actual volatility. Otherwise we use
    the legacy MA-based rules so backward compat is preserved.
    """
    if ticker_frame is None or ticker_frame.empty or "close" not in ticker_frame.columns:
        return None

    if atr_value is not None and atr_value > 0:
        atr_stop = _atr_stop(ticker_frame, atr_value=atr_value, multiplier=atr_multiplier)
        if atr_stop is not None:
            return atr_stop

    close = ticker_frame["close"]

    if direction_action in _HEALTHY_ACTIONS:
        return _healthy_stop(close)
    return _weakening_stop(ticker_frame)


def _atr_stop(frame: pd.DataFrame, *, atr_value: float, multiplier: float) -> Decimal | None:
    """``close - multiplier * ATR``. Returns None if last close is missing
    or the resulting stop is non-positive (would be a pathological case
    of multiplier × ATR > price, never happens in practice)."""
    last_close = last_float(frame["close"])
    if last_close is None:
        return None
    stop_raw = last_close - multiplier * atr_value
    if stop_raw <= 0:
        return None
    return _quantize(stop_raw)


def _healthy_stop(close: pd.Series) -> Decimal | None:
    if len(close) < 200:
        return None
    ma200 = last_float(sma(close, 200))
    if ma200 is None:
        return None
    return _quantize(ma200 * _BUFFER)


def _weakening_stop(frame: pd.DataFrame) -> Decimal | None:
    close = frame["close"]
    if len(close) >= 20:
        bb = bollinger_bands(close, length=20, std_mult=2.0)
        lower = last_float(bb.lower)
        if lower is not None:
            return _quantize(lower * _BUFFER)

    # Fallback: 5-day low × 0.97. Requires ``low`` column; failing that,
    # use close-as-low which is equivalent for daily-close data.
    series = frame["low"] if "low" in frame.columns else close
    tail = series.dropna().tail(5)
    if tail.empty:
        return None
    low_5d = float(tail.min())
    return _quantize(low_5d * _BUFFER)


def _quantize(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_QUANTIZER, rounding=ROUND_HALF_UP)

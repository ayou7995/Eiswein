"""Dynamic stop-loss calculator (I16).

Rules (from staff review):

* Healthy trend (action ∈ {STRONG_BUY, BUY, HOLD}):
    ``stop_loss = 200MA × 0.97``
* Weakening trend (action ∈ {WATCH, REDUCE, EXIT}):
    ``stop_loss = Bollinger-lower × 0.97``
  with fallback to ``min(last 5 lows) × 0.97`` when BB isn't computable.

Returns ``None`` when data is insufficient for the branch chosen —
caller persists ``NULL`` and the UI shows "─".

The multiplier 0.97 bakes in a 3% buffer beneath the reference MA so
a one-day wick doesn't trigger an exit — practical Sherry-style trailing
stop, not a theoretical optimum.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from app.indicators._helpers import bollinger_bands, last_float, sma
from app.signals.types import ActionCategory

if TYPE_CHECKING:
    import pandas as pd

_BUFFER: Final[float] = 0.97
_QUANTIZER: Final[Decimal] = Decimal("0.0001")
_HEALTHY_ACTIONS: Final[frozenset[ActionCategory]] = frozenset(
    {ActionCategory.STRONG_BUY, ActionCategory.BUY, ActionCategory.HOLD}
)


def compute_stop_loss(
    ticker_frame: pd.DataFrame,
    *,
    direction_action: ActionCategory,
) -> Decimal | None:
    """Compute the stop-loss price for the ticker given the D1a action.

    Healthy branch uses 200MA — a classic Sherry trailing stop that
    only triggers on a decisive break of the long-term trend. Weakening
    branch uses Bollinger lower (or 5-day low fallback) so the stop
    respects recent volatility rather than a far-below MA.
    """
    if ticker_frame is None or ticker_frame.empty or "close" not in ticker_frame.columns:
        return None

    close = ticker_frame["close"]

    if direction_action in _HEALTHY_ACTIONS:
        return _healthy_stop(close)
    return _weakening_stop(ticker_frame)


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

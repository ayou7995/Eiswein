"""3-tier entry price calculator (I15).

Tiers:

* ``aggressive``   — 50MA (short-term support — aggressive entry on pullback).
* ``ideal``        — 20MA / Bollinger middle band.
* ``conservative`` — 200MA, or Bollinger lower band when clearly below 200MA.

Each tier is quantized to a 4-decimal :class:`Decimal` so the API
response and DB column both round-trip exactly (same pattern used by
DailyPrice.close). Missing history → ``None`` for that tier; the UI
renders it as "─" rather than a bogus numeric placeholder.

The ``timing_modifier`` parameter is accepted for future UI emphasis
hooks (highlight "積極進場" when favorable, dim it when unfavorable).
This module does not currently change the numeric tiers based on
timing — that's a frontend presentation concern.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from app.indicators._helpers import bollinger_bands, last_float, sma
from app.signals.types import EntryTiers, TimingModifier

if TYPE_CHECKING:
    import pandas as pd

_QUANTIZER: Final[Decimal] = Decimal("0.0001")
_BB_BELOW_MA200_TOLERANCE_PCT: Final[float] = 1.0


def compute_entry_tiers(
    ticker_frame: pd.DataFrame,
    *,
    timing_modifier: TimingModifier = TimingModifier.MIXED,
) -> EntryTiers:
    """Derive the 3-tier entry suggestion from a ticker OHLCV frame.

    Returns ``EntryTiers(None, None, None)`` when the frame lacks a
    usable ``close`` series. Individual tiers may be None (e.g.
    conservative requires 200 bars of history).
    """
    _ = timing_modifier  # Kept in signature for future UI cues.
    aggressive: Decimal | None = None
    ideal: Decimal | None = None
    conservative: Decimal | None = None

    if ticker_frame is None or ticker_frame.empty or "close" not in ticker_frame.columns:
        return EntryTiers(aggressive=None, ideal=None, conservative=None)

    close = ticker_frame["close"]

    ma50 = last_float(sma(close, 50)) if len(close) >= 50 else None
    ma20 = last_float(sma(close, 20)) if len(close) >= 20 else None
    ma200 = last_float(sma(close, 200)) if len(close) >= 200 else None

    if ma50 is not None:
        aggressive = _quantize(ma50)

    # Bollinger middle(20) ≡ SMA(20); use SMA(20) so we don't compute
    # the Bollinger bands just to pull out the middle. Bollinger lower
    # is only needed when 200MA isn't a reasonable conservative anchor
    # (price is clearly below 200MA, so 200MA would be an unreachable
    # wishful-thinking floor).
    if ma20 is not None:
        ideal = _quantize(ma20)

    conservative = _pick_conservative(close=close, ma200=ma200)

    return EntryTiers(aggressive=aggressive, ideal=ideal, conservative=conservative)


def _pick_conservative(*, close: pd.Series, ma200: float | None) -> Decimal | None:
    """Conservative tier: 200MA normally, BB-lower when price < 200MA.

    ``_BB_BELOW_MA200_TOLERANCE_PCT`` is a small buffer so we don't
    flip between anchors on a price that's just barely under the 200MA
    (noisy). Must be >1% below 200MA to switch to BB-lower.
    """
    if ma200 is None:
        return None

    last_price = last_float(close)
    if last_price is None:
        return _quantize(ma200)

    threshold = ma200 * (1.0 - _BB_BELOW_MA200_TOLERANCE_PCT / 100.0)
    if last_price >= threshold:
        return _quantize(ma200)

    # Price clearly below 200MA → use BB lower band (if computable).
    if len(close) < 20:
        return _quantize(ma200)
    bb = bollinger_bands(close, length=20, std_mult=2.0)
    lower = last_float(bb.lower)
    if lower is None:
        return _quantize(ma200)
    return _quantize(lower)


def _quantize(value: float) -> Decimal:
    """Quantize a float to 4 decimal places using ROUND_HALF_UP.

    ``Decimal(str(value))`` first — not ``Decimal(value)`` — so the
    base Decimal starts from the repr representation rather than the
    binary float, avoiding the classic ``Decimal(0.1) ==
    Decimal("0.1000000000000000055511151231257827021181583404541015625")``
    trap.
    """
    return Decimal(str(value)).quantize(_QUANTIZER, rounding=ROUND_HALF_UP)

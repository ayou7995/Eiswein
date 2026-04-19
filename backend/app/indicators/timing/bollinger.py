"""Bollinger Bands (20-period, 2σ) positional indicator (C6).

Signal table:
* close > upper  → RED    (超買警示)
* close < lower  → GREEN  (超賣機會)
* close ≈ middle → YELLOW (中軌徘徊)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import bollinger_bands, last_float
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "bollinger"
_LENGTH = 20


def compute_bollinger(frame: "pd.DataFrame", context: "IndicatorContext") -> IndicatorResult:
    _ = context
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)
    close = frame["close"]
    if len(close) < _LENGTH + 1:
        return insufficient_result(NAME, detail={"bars": len(close)})

    bands = bollinger_bands(close, length=_LENGTH)
    upper = last_float(bands.upper)
    middle = last_float(bands.middle)
    lower = last_float(bands.lower)
    price = last_float(close)

    if upper is None or middle is None or lower is None or price is None:
        return insufficient_result(NAME)

    signal, short_label = _classify(price=price, upper=upper, lower=lower, middle=middle)
    band_width = upper - lower if upper > lower else 0.0
    position = ((price - lower) / band_width) if band_width > 0 else 0.5

    return IndicatorResult(
        name=NAME,
        value=price,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "price": price,
            "position": position,
            "band_width": band_width,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(
    *,
    price: float,
    upper: float,
    lower: float,
    middle: float,
) -> tuple[SignalToneLiteral, str]:
    if price > upper:
        return SignalTone.RED, "布林帶上緣超買"
    if price < lower:
        return SignalTone.GREEN, "布林帶下緣超賣"
    if price >= middle:
        return SignalTone.YELLOW, "布林帶中軌上方"
    return SignalTone.YELLOW, "布林帶中軌下方"

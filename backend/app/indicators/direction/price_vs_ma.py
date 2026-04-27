"""Per-ticker price vs 50/200 MA.

Mirrors the SPX MA decision table (C1) but applied to an individual
ticker frame.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import detect_ma_crosses, last_float, sma
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "price_vs_ma"
_MIN_BARS = 200


def compute_price_vs_ma(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)
    close = frame["close"]
    if len(close) < _MIN_BARS:
        return insufficient_result(NAME, detail={"bars": len(close)})

    ma50_series = sma(close, 50)
    ma200_series = sma(close, 200)
    price = last_float(close)
    ma50 = last_float(ma50_series)
    ma200 = last_float(ma200_series)

    if price is None or ma50 is None or ma200 is None:
        return insufficient_result(NAME)

    signal, short_label = _classify(price=price, ma50=ma50, ma200=ma200)
    golden_cross, death_cross = detect_ma_crosses(ma50_series, ma200_series)
    return IndicatorResult(
        name=NAME,
        value=price,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "price": price,
            "ma50": ma50,
            "ma200": ma200,
            "price_vs_ma50_pct": ((price - ma50) / ma50) * 100.0,
            "price_vs_ma200_pct": ((price - ma200) / ma200) * 100.0,
            "golden_cross_10d": golden_cross,
            "death_cross_10d": death_cross,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(*, price: float, ma50: float, ma200: float) -> tuple[SignalToneLiteral, str]:
    """Same 3-tier rule as the SPX market regime indicator (C1).

    Labels are intentionally short and parallel to ``spx_ma`` so the
    per-ticker UI can reuse the same Pros/Cons rendering — the surrounding
    page context already tells the user this is about an individual stock.
    """
    if price > ma50 and price > ma200:
        return SignalTone.GREEN, "多頭排列"
    # Price at-or-above the long-term MA is holding the line — YELLOW,
    # not RED. RED means strictly below 200MA.
    if price >= ma200:
        return SignalTone.YELLOW, "中期多頭、短期偏弱"
    return SignalTone.RED, "空頭趨勢"

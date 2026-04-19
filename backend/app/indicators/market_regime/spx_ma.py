"""SPX 50/200 MA trend indicator (C1).

Decision table:
* close > 50MA and close > 200MA  → GREEN  (強勢多頭)
* close > 200MA but not > 50MA    → YELLOW (中期多頭)
* close < 200MA                   → RED    (空頭趨勢)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import last_float, sma
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "spx_ma"
_MIN_BARS_REQUIRED = 200


def compute_spx_ma(frame: "pd.DataFrame", context: "IndicatorContext") -> IndicatorResult:
    """Compute SPX 50/200 MA regime on the SPX close series.

    Pure function: called with the SPX frame from ``context.spx_frame``
    by the orchestrator; keeping ``frame`` as a parameter (rather than
    reaching into context) leaves the function testable in isolation.
    """
    _ = context  # Unused here — signature kept uniform with other indicators.
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)
    close = frame["close"]
    if len(close) < _MIN_BARS_REQUIRED:
        return insufficient_result(NAME, detail={"bars": len(close)})

    ma50_series = sma(close, 50)
    ma200_series = sma(close, 200)

    price = last_float(close)
    ma50 = last_float(ma50_series)
    ma200 = last_float(ma200_series)

    if price is None or ma50 is None or ma200 is None:
        return insufficient_result(NAME)

    signal, short_label = _classify(price=price, ma50=ma50, ma200=ma200)
    golden_cross, death_cross = _detect_crosses(ma50_series, ma200_series)

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
    if price > ma50 and price > ma200:
        return SignalTone.GREEN, "SPX 多頭排列"
    if price > ma200:
        return SignalTone.YELLOW, "SPX 中期多頭、短期偏弱"
    return SignalTone.RED, "SPX 空頭趨勢"


def _detect_crosses(
    ma50: "pd.Series",
    ma200: "pd.Series",
    lookback: int = 10,
) -> tuple[bool, bool]:
    """Detect a bullish/bearish 50×200 cross within the last ``lookback`` bars.

    Returns ``(golden_cross, death_cross)`` — only one should be
    truthy in normal market action, but both may be false when the
    lines aren't near each other.
    """
    joined = ma50.to_frame("s50").join(ma200.to_frame("s200"), how="inner").dropna()
    if len(joined) < 2:
        return False, False
    joined = joined.tail(lookback + 1)
    if len(joined) < 2:
        return False, False
    diff = joined["s50"] - joined["s200"]
    bullish = (diff.shift(1) <= 0) & (diff > 0)
    bearish = (diff.shift(1) >= 0) & (diff < 0)
    return bool(bullish.any()), bool(bearish.any())

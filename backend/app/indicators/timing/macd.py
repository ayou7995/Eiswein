"""MACD (12, 26, 9) crossover detection (C7).

The *latest* crossover within the last 3 bars drives the signal —
anything older is considered a stale condition (neutral YELLOW).

Signal table:
* bullish cross (MACD crossed above signal line) → GREEN
* bearish cross (MACD crossed below signal line) → RED
* neither recent                                  → YELLOW
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import last_float
from app.indicators._helpers import macd as compute_macd_series
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "macd"
_MIN_BARS = 35  # 26 slow EMA + 9 signal window
_CROSS_LOOKBACK = 3


def compute_macd(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)
    close = frame["close"]
    if len(close) < _MIN_BARS:
        return insufficient_result(NAME, detail={"bars": len(close)})

    result = compute_macd_series(close)
    macd_value = last_float(result.macd_line)
    signal_value = last_float(result.signal_line)
    histogram_value = last_float(result.histogram)

    if macd_value is None or signal_value is None or histogram_value is None:
        return insufficient_result(NAME)

    cross = _detect_recent_cross(result.macd_line, result.signal_line, _CROSS_LOOKBACK)
    signal, short_label = _classify(cross=cross, histogram=histogram_value)

    return IndicatorResult(
        name=NAME,
        value=macd_value,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "macd": macd_value,
            "signal": signal_value,
            "histogram": histogram_value,
            "recent_cross": cross,
            "cross_lookback_bars": _CROSS_LOOKBACK,
        },
        computed_at=datetime.now(UTC),
    )


def _detect_recent_cross(
    macd_line: pd.Series,
    signal_line: pd.Series,
    lookback: int,
) -> str:
    """Return ``bullish`` / ``bearish`` / ``none`` based on the latest
    cross within the lookback window.
    """
    aligned = (macd_line - signal_line).dropna()
    if len(aligned) < 2:
        return "none"
    recent = aligned.tail(lookback + 1)
    if len(recent) < 2:
        return "none"
    # Check each adjacent pair for a sign-change.
    for i in range(len(recent) - 1, 0, -1):
        prev = recent.iloc[i - 1]
        curr = recent.iloc[i]
        if prev <= 0 < curr:
            return "bullish"
        if prev >= 0 > curr:
            return "bearish"
    return "none"


def _classify(*, cross: str, histogram: float) -> tuple[SignalToneLiteral, str]:
    if cross == "bullish":
        return SignalTone.GREEN, "MACD 金叉"
    if cross == "bearish":
        return SignalTone.RED, "MACD 死叉"
    if histogram > 0:
        return SignalTone.YELLOW, "MACD 柱狀轉正"
    return SignalTone.YELLOW, "MACD 柱狀轉負"

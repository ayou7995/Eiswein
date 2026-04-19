"""RSI(14) daily + weekly via Wilder's smoothing (C2).

Weekly RSI is derived by resampling daily closes into
``W-FRI`` (Friday-anchored weekly) bars, then re-applying the same
Wilder-smoothed RSI formula.

Signal table:
* daily > 70 AND weekly > 70  → RED    (超買確認)
* daily < 30 AND weekly < 30  → GREEN  (超賣確認)
* daily > 70, weekly ≤ 70    → YELLOW (短線超買)
* daily < 30, weekly ≥ 30    → YELLOW (短線超賣)
* else                        → YELLOW (中性)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import last_float, wilder_rsi
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "rsi"
_LENGTH = 14
_MIN_DAILY_BARS = _LENGTH + 1
_MIN_WEEKLY_BARS = _LENGTH * 7 + 7  # ~105 daily bars = ~15 weekly bars


def compute_rsi(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)

    close = frame["close"].astype("float64")
    if len(close) < _MIN_DAILY_BARS:
        return insufficient_result(NAME, detail={"bars": len(close)})

    daily_rsi = wilder_rsi(close, _LENGTH)
    daily_value = last_float(daily_rsi)
    if daily_value is None:
        return insufficient_result(NAME)

    weekly_value: float | None = None
    if len(close) >= _MIN_WEEKLY_BARS:
        weekly_close = close.resample("W-FRI").last().dropna()
        if len(weekly_close) >= _MIN_DAILY_BARS:
            weekly_rsi = wilder_rsi(weekly_close, _LENGTH)
            weekly_value = last_float(weekly_rsi)

    signal, short_label = _classify(daily=daily_value, weekly=weekly_value)

    return IndicatorResult(
        name=NAME,
        value=daily_value,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "daily_rsi": daily_value,
            "weekly_rsi": weekly_value,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(*, daily: float, weekly: float | None) -> tuple[SignalToneLiteral, str]:
    if weekly is not None and daily > 70 and weekly > 70:
        return SignalTone.RED, f"RSI 超買 {daily:.0f}（週線確認）"
    if weekly is not None and daily < 30 and weekly < 30:
        return SignalTone.GREEN, f"RSI 超賣 {daily:.0f}（週線確認）"
    if daily > 70:
        return SignalTone.YELLOW, f"RSI 短線超買 {daily:.0f}"
    if daily < 30:
        return SignalTone.YELLOW, f"RSI 短線超賣 {daily:.0f}"
    return SignalTone.YELLOW, f"RSI 中性 {daily:.0f}"

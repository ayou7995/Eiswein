"""Volume anomaly detector (C4).

Today's volume is compared against the 20-day SMA of **prior** 20
days (excluding today). A spike is ``today > 2 * avg``.

Signal table:
* spike AND close > prior_close → GREEN  (放量上漲)
* spike AND close < prior_close → RED    (放量下跌)
* spike AND flat close          → YELLOW (放量但方向不明)
* no spike                      → YELLOW (量能正常)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "volume_anomaly"
_WINDOW = 20
_SPIKE_MULTIPLIER = 2.0


def compute_volume_anomaly(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty:
        return insufficient_result(NAME)
    if not {"close", "volume"}.issubset(frame.columns):
        return insufficient_result(NAME)
    if len(frame) < _WINDOW + 2:
        return insufficient_result(NAME, detail={"bars": len(frame)})

    volume = frame["volume"].astype("float64")
    close = frame["close"].astype("float64")

    today_volume = float(volume.iloc[-1])
    # Prior 20 days → exclude today (iloc[-1]).
    prior_volume = volume.iloc[-(_WINDOW + 1) : -1]
    avg_volume = float(prior_volume.mean())

    ratio = today_volume / avg_volume if avg_volume > 0 else 0.0
    spike = ratio >= _SPIKE_MULTIPLIER

    today_close = float(close.iloc[-1])
    prior_close = float(close.iloc[-2])
    close_direction = today_close - prior_close

    signal, short_label = _classify(spike=spike, ratio=ratio, direction=close_direction)

    return IndicatorResult(
        name=NAME,
        value=ratio,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "today_volume": today_volume,
            "avg_volume_20d": avg_volume,
            "ratio": ratio,
            "spike": spike,
            "price_change": close_direction,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(
    *,
    spike: bool,
    ratio: float,
    direction: float,
) -> tuple[SignalToneLiteral, str]:
    if not spike:
        return SignalTone.YELLOW, f"量能正常 ({ratio:.1f}×)"
    if direction > 0:
        return SignalTone.GREEN, f"放量上漲 ({ratio:.1f}×)"
    if direction < 0:
        return SignalTone.RED, f"放量下跌 ({ratio:.1f}×)"
    return SignalTone.YELLOW, f"放量但方向不明 ({ratio:.1f}×)"

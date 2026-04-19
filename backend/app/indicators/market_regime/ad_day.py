"""A/D Day Count over 25 trading days (C3).

Strict O'Neil:
* Up day with ``volume > prev_volume``  → Accumulation
* Down day with ``volume > prev_volume`` → Distribution
* Flat-to-down volume → Neutral (not counted)

Signal table:
* net (accum - distrib) ≥ +3 → GREEN
* |net| ≤ 2                 → YELLOW
* net ≤ -3                  → RED
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

NAME = "ad_day"
_WINDOW = 25


def compute_ad_day(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty:
        return insufficient_result(NAME)
    required = {"open", "close", "volume"}
    if not required.issubset(frame.columns):
        return insufficient_result(NAME)
    # Need prior-day volume for the first window bar → +1.
    if len(frame) < _WINDOW + 1:
        return insufficient_result(NAME, detail={"bars": len(frame)})

    window = frame.tail(_WINDOW + 1).copy()
    close = window["close"].astype("float64")
    open_ = window["open"].astype("float64")
    volume = window["volume"].astype("float64")
    prev_volume = volume.shift(1)

    is_up = close > open_
    is_down = close < open_
    volume_expanding = volume > prev_volume

    recent = window.iloc[1:]  # discard first bar used only for prev_volume
    accum_mask = (is_up & volume_expanding).loc[recent.index]
    distrib_mask = (is_down & volume_expanding).loc[recent.index]

    accum_count = int(accum_mask.sum())
    distrib_count = int(distrib_mask.sum())
    net = accum_count - distrib_count

    signal, short_label = _classify(net)

    return IndicatorResult(
        name=NAME,
        value=float(net),
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "accum_count": accum_count,
            "distrib_count": distrib_count,
            "net": net,
            "window_days": _WINDOW,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(net: int) -> tuple[SignalToneLiteral, str]:
    if net >= 3:
        return SignalTone.GREEN, f"A/D Day 淨 +{net}（資金流入）"
    if net <= -3:
        return SignalTone.RED, f"A/D Day 淨 {net}（資金流出）"
    return SignalTone.YELLOW, f"A/D Day 淨 {net:+d}（觀望）"

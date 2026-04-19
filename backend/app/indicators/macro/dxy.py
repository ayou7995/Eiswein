"""DXY direction via 20-day SMA slope + 5-day streak (C9).

Note: We use the FRED ``DTWEXBGS`` series (Trade-Weighted USD Broad
Index) as a DXY proxy because FRED does not republish raw DXY. The
README documents this substitution.

Signal table (per C9):
* 5 consecutive rising 20MA days  → RED    (DXY 走強對科技股不利)
* 5 consecutive falling 20MA days → GREEN  (DXY 走弱對科技股有利)
* otherwise (including flat)      → YELLOW (方向不明)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

from app.indicators._helpers import sma
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "dxy"
_MACRO_SERIES = "DTWEXBGS"
_SMA_WINDOW = 20
_STREAK = 5


def compute_dxy(frame: pd.DataFrame, context: "IndicatorContext") -> IndicatorResult:
    _ = frame
    dxy = context.macro_frames.get(_MACRO_SERIES)
    if dxy is None or dxy.empty or "value" not in dxy.columns:
        return insufficient_result(NAME)

    series = dxy["value"].astype("float64").dropna()
    # Need 20-bar SMA + 5 more bars for the streak comparison.
    if len(series) < _SMA_WINDOW + _STREAK + 1:
        return insufficient_result(NAME, detail={"bars": len(series)})

    ma = sma(series, _SMA_WINDOW).dropna()
    if len(ma) < _STREAK + 1:
        return insufficient_result(NAME)

    tail = ma.tail(_STREAK + 1)
    diffs = tail.diff().dropna()

    rising_streak = bool((diffs > 0).all())
    falling_streak = bool((diffs < 0).all())

    signal, short_label = _classify(rising=rising_streak, falling=falling_streak)

    return IndicatorResult(
        name=NAME,
        value=float(tail.iloc[-1]),
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "ma20": float(tail.iloc[-1]),
            "streak_rising": rising_streak,
            "streak_falling": falling_streak,
            "streak_days": _STREAK,
            "ma20_change_last_5d": float(tail.iloc[-1] - tail.iloc[0]),
        },
        computed_at=datetime.now(UTC),
    )


def _classify(*, rising: bool, falling: bool) -> tuple[SignalToneLiteral, str]:
    if rising:
        return SignalTone.RED, "DXY 走強（科技股逆風）"
    if falling:
        return SignalTone.GREEN, "DXY 走弱（科技股順風）"
    return SignalTone.YELLOW, "DXY 方向不明"

"""VIX level + 10-day trend indicator.

Consumes the ``VIXCLS`` macro series from ``context.macro_frames``.
Each macro frame is expected to have a single ``value`` column indexed
by date — matching the :class:`~app.db.models.MacroIndicator` row
shape.

Level tiers:
* level ≤ 15        → YELLOW (複滿)
* 15 < level ≤ 20   → GREEN  (正常)
* 20 < level ≤ 25   → YELLOW (警戒)
* level > 25        → RED    (恐慌)
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

NAME = "vix"
_MACRO_SERIES = "VIXCLS"
_TREND_WINDOW = 10
_TREND_FLAT_BAND = 1.0


def compute_vix(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    """Signature accepts ``frame`` for interface uniformity; the VIX
    series actually lives in ``context.macro_frames``. Orchestrator
    passes an empty frame — keeping the positional arg consistent with
    the other indicators keeps the orchestrator's call loop uniform.
    """
    _ = frame
    vix = context.macro_frames.get(_MACRO_SERIES)
    if vix is None or vix.empty or "value" not in vix.columns:
        return insufficient_result(NAME)
    series = vix["value"].astype("float64").dropna()
    if len(series) < _TREND_WINDOW + 1:
        return insufficient_result(NAME, detail={"bars": len(series)})

    level = float(series.iloc[-1])
    prior = float(series.iloc[-(_TREND_WINDOW + 1)])
    ten_day_change = level - prior

    trend = _classify_trend(ten_day_change)
    signal, short_label = _classify_level(level, trend)

    return IndicatorResult(
        name=NAME,
        value=level,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "level": level,
            "ten_day_change": ten_day_change,
            "trend": trend,
        },
        computed_at=datetime.now(UTC),
    )


def _classify_trend(change: float) -> str:
    if change > _TREND_FLAT_BAND:
        return "rising"
    if change < -_TREND_FLAT_BAND:
        return "falling"
    return "flat"


def _classify_level(level: float, trend: str) -> tuple[SignalToneLiteral, str]:
    if level <= 15.0:
        return SignalTone.YELLOW, f"VIX 偏低 {level:.1f}（複滿警戒）"
    if level <= 20.0:
        return SignalTone.GREEN, f"VIX 正常 {level:.1f}"
    if level <= 25.0:
        return SignalTone.YELLOW, f"VIX 警戒 {level:.1f}"
    emphasis = "走高" if trend == "rising" else "偏高"
    return SignalTone.RED, f"VIX {emphasis} {level:.1f}（恐慌）"

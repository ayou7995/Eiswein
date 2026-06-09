"""VIX level + 10-day trend indicator.

Consumes the ``VIXCLS`` macro series from ``context.macro_frames``.
Each macro frame is expected to have a single ``value`` column indexed
by date — matching the :class:`~app.db.models.MacroIndicator` row
shape.

Zone tiers (industry convention; aligned with the chart-series builder
in ``app/api/v1/_market_series.py``):

* level <  12        → YELLOW (自滿；過度樂觀，反向訊號)
* 12 ≤ level ≤ 20    → GREEN  (正常)
* 20 < level ≤ 30    → YELLOW (警戒；壓力升高)
* level > 30         → RED    (恐慌；賣壓主導)

Detail also includes the 1-year (252 trading-day) percentile rank of
the current level — useful for "is this high *for VIX*" framing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of, percentile_in_window
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
_PERCENTILE_WINDOW = 252

_LOW_THRESHOLD = 12.0
_NORMAL_HIGH = 20.0
_ELEVATED_HIGH = 30.0


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
    data_as_of = frame_as_of(vix)
    series = vix["value"].astype("float64").dropna()
    if len(series) < _TREND_WINDOW + 1:
        return insufficient_result(
            NAME, detail={"bars": len(series)}, data_as_of=data_as_of
        )

    level = float(series.iloc[-1])
    prior = float(series.iloc[-(_TREND_WINDOW + 1)])
    ten_day_change = level - prior

    trend = _classify_trend(ten_day_change)
    signal, short_label = _classify_level(level, trend)
    percentile_1y = percentile_in_window(series, _PERCENTILE_WINDOW)

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
            "percentile_1y": percentile_1y,
            "threshold_low": _LOW_THRESHOLD,
            "threshold_normal_high": _NORMAL_HIGH,
            "threshold_elevated_high": _ELEVATED_HIGH,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _classify_trend(change: float) -> str:
    if change > _TREND_FLAT_BAND:
        return "rising"
    if change < -_TREND_FLAT_BAND:
        return "falling"
    return "flat"


def _classify_level(level: float, trend: str) -> tuple[SignalToneLiteral, str]:
    _ = trend  # Trend is surfaced in detail; the headline is level + zone only.
    if level < _LOW_THRESHOLD:
        return SignalTone.YELLOW, f"VIX {level:.1f}（偏低自滿）"
    if level <= _NORMAL_HIGH:
        return SignalTone.GREEN, f"VIX {level:.1f}（正常）"
    if level <= _ELEVATED_HIGH:
        return SignalTone.YELLOW, f"VIX {level:.1f}（警戒）"
    return SignalTone.RED, f"VIX {level:.1f}（恐慌）"

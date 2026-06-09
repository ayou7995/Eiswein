"""CBOE SKEW Index — perceived left-tail risk (short-term, votes).

Reads ``^SKEW`` daily levels from ``context.skew_frame`` (loaded by
:mod:`app.ingestion.indicators` via the same SYSTEM_SYMBOLS bulk path
as RSP / HYG / IEF). The CBOE Skew Index measures the cost of out-of-
the-money S&P 500 puts relative to ATM puts — i.e. how much institu-
tional money is paying for crash protection.

Level interpretation (industry convention):

* level ≤ 130        → GREEN  (低尾部風險定價，無顯著恐慌避險)
* 130 < level < 145  → YELLOW (尾部風險上升，留意)
* level ≥ 145        → RED    (顯著尾部風險定價／機構主動避險)

Why this is orthogonal to VIX and worth a vote:
VIX prices ATM 30-day implied vol — the "consensus expected move".
SKEW prices the *tail* of the distribution. A typical 2007/2018/Feb-2020
pattern is SKEW grinding higher (institutions quietly bid OTM puts)
while VIX stays calm. The two diverge at exactly the moments where
a single-indicator posture would miss the build-up.

Detail also includes the 1-year percentile rank so the "is this high
*for SKEW*" framing comes through in the UI.
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
    from app.indicators.context import IndicatorContext

NAME = "skew"

_PERCENTILE_WINDOW = 252
_TREND_WINDOW = 10
_TREND_FLAT_BAND = 1.0

_NORMAL_HIGH = 130.0
_ELEVATED_HIGH = 145.0
_MIN_BARS = _TREND_WINDOW + 1


def compute_skew(_frame: object, context: IndicatorContext) -> IndicatorResult:
    skew = context.skew_frame
    if skew is None or skew.empty or "close" not in skew.columns:
        return insufficient_result(NAME)
    series = skew["close"].astype("float64").dropna()
    data_as_of = frame_as_of(skew)
    if len(series) < _MIN_BARS:
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
    _ = trend  # Trend ships in detail; the headline is level + zone only.
    if level <= _NORMAL_HIGH:
        return SignalTone.GREEN, f"SKEW {level:.0f}（尾部風險低）"
    if level < _ELEVATED_HIGH:
        return SignalTone.YELLOW, f"SKEW {level:.0f}（尾部風險上升）"
    return SignalTone.RED, f"SKEW {level:.0f}（機構避險）"


__all__ = ["NAME", "compute_skew"]

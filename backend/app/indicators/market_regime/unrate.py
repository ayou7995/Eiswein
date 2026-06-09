"""US unemployment rate + Sahm Rule recession trigger (long-term, votes).

Reads the ``UNRATE`` series from ``context.macro_frames`` (FRED). UNRATE
is the headline civilian unemployment rate, published monthly.

The vote is driven by the **Sahm Rule** (Claudia Sahm, 2019):

    sahm_value = 3-month moving avg of UNRATE
                 minus the trailing 12-month MINIMUM of UNRATE

When ``sahm_value`` crosses ``0.5``, every U.S. recession since 1959 has
already begun. False positives: 0. False negatives: 0. It's the single
most reliable real-time recession trigger published — strictly better
than the 10Y-2Y yield spread (which leads recessions by 6-18 months but
also throws false signals).

Zones:

* sahm < 0.30        → GREEN  (失業率穩定，無衰退訊號)
* 0.30 ≤ sahm < 0.50 → YELLOW (警戒區，距離 Sahm Rule 觸發 < 0.20)
* sahm ≥ 0.50        → RED    (Sahm Rule 觸發，衰退已在發生)

Sahm Rule is the *current* recession detector; yield_spread is the
*future* one. Both belong in the long-term bucket and they convey
genuinely independent signals — Sahm flips well after yield_spread.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "unrate"
_MACRO_SERIES = "UNRATE"
_SAHM_3M_WINDOW = 3
_SAHM_12M_WINDOW = 12
_SAHM_WARNING = 0.30
_SAHM_TRIGGER = 0.50
_MIN_MONTHS = _SAHM_12M_WINDOW + 1


def compute_unrate(_frame: object, context: IndicatorContext) -> IndicatorResult:
    unrate = context.macro_frames.get(_MACRO_SERIES)
    if unrate is None or unrate.empty or "value" not in unrate.columns:
        return insufficient_result(NAME)
    series = unrate["value"].astype("float64").dropna()
    data_as_of = frame_as_of(unrate)
    if len(series) < _MIN_MONTHS:
        return insufficient_result(
            NAME, detail={"months": len(series)}, data_as_of=data_as_of
        )

    current_rate = float(series.iloc[-1])
    prior_rate = float(series.iloc[-2])
    three_mma = float(series.iloc[-_SAHM_3M_WINDOW:].mean())
    twelve_month_low = float(series.iloc[-_SAHM_12M_WINDOW:].min())
    sahm_value = three_mma - twelve_month_low

    signal, short_label = _classify(sahm_value=sahm_value, current_rate=current_rate)

    return IndicatorResult(
        name=NAME,
        value=current_rate,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "current_rate": current_rate,
            "prior_month_rate": prior_rate,
            "three_month_avg": three_mma,
            "twelve_month_low": twelve_month_low,
            "sahm_value": sahm_value,
            "sahm_distance_to_trigger": _SAHM_TRIGGER - sahm_value,
            "threshold_warning": _SAHM_WARNING,
            "threshold_trigger": _SAHM_TRIGGER,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _classify(*, sahm_value: float, current_rate: float) -> tuple[SignalToneLiteral, str]:
    if sahm_value >= _SAHM_TRIGGER:
        return (
            SignalTone.RED,
            f"失業率 {current_rate:.1f}%，Sahm {sahm_value:+.2f}（衰退訊號）",
        )
    if sahm_value >= _SAHM_WARNING:
        return (
            SignalTone.YELLOW,
            f"失業率 {current_rate:.1f}%，Sahm {sahm_value:+.2f}（警戒）",
        )
    return (
        SignalTone.GREEN,
        f"失業率 {current_rate:.1f}%，Sahm {sahm_value:+.2f}（健康）",
    )


__all__ = ["NAME", "compute_unrate"]

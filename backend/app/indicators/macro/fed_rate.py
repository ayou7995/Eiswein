"""Fed Funds Rate level + 30-day delta.

Consumes FRED ``FEDFUNDS`` series.

Signal table:
* delta < -0.25 → GREEN  (降息循環)
* |delta| ≤ 0.25 → YELLOW (持平)
* delta >  0.25 → RED    (升息循環)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "fed_rate"
_MACRO_SERIES = "FEDFUNDS"
_DELTA_DAYS = 30
_CUT_THRESHOLD = -0.25
_HIKE_THRESHOLD = 0.25


def compute_fed_rate(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = frame
    series_frame = context.macro_frames.get(_MACRO_SERIES)
    if series_frame is None or series_frame.empty or "value" not in series_frame.columns:
        return insufficient_result(NAME)

    # FEDFUNDS is published monthly — normalize to a date-indexed series.
    series = series_frame["value"].astype("float64").dropna().sort_index()
    if series.empty:
        return insufficient_result(NAME)

    current = float(series.iloc[-1])
    latest_ts = pd.Timestamp(series.index[-1])
    cutoff = latest_ts - pd.Timedelta(days=_DELTA_DAYS)
    historical = series.loc[series.index <= cutoff]
    if historical.empty:
        return insufficient_result(NAME, detail={"reason": "no_history_for_delta"})

    prior = float(historical.iloc[-1])
    delta = current - prior

    signal, short_label = _classify(current=current, delta=delta)

    return IndicatorResult(
        name=NAME,
        value=current,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "current": current,
            "prior_30d": prior,
            "delta_30d": delta,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(*, current: float, delta: float) -> tuple[SignalToneLiteral, str]:
    if delta < _CUT_THRESHOLD:
        return SignalTone.GREEN, f"Fed 降息中（{current:.2f}%，Δ{delta:+.2f}）"
    if delta > _HIKE_THRESHOLD:
        return SignalTone.RED, f"Fed 升息中（{current:.2f}%，Δ{delta:+.2f}）"
    return SignalTone.YELLOW, f"Fed 利率持平（{current:.2f}%）"

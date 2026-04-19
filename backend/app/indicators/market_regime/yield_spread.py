"""10Y-2Y yield spread (C8).

Consumes ``DGS10`` and ``DGS2`` macro series. Pair-wise difference at
the most recent common date is the headline value.

Signal tiers (C8):
* spread > 0.2 → GREEN  (健康)
* 0 ≤ spread ≤ 0.2 → YELLOW (趨平)
* spread ≤ 0 → RED    (倒掛)

``detail`` includes whether the spread transitioned across the zero
line within the last 20 trading days — useful for the UI's "recent
inversion" callout (consumer in Phase 4).
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

NAME = "yield_spread"
_SERIES_10Y = "DGS10"
_SERIES_2Y = "DGS2"


def compute_yield_spread(frame: pd.DataFrame, context: "IndicatorContext") -> IndicatorResult:
    _ = frame
    ten = context.macro_frames.get(_SERIES_10Y)
    two = context.macro_frames.get(_SERIES_2Y)
    if ten is None or two is None or ten.empty or two.empty:
        return insufficient_result(NAME)
    if "value" not in ten.columns or "value" not in two.columns:
        return insufficient_result(NAME)

    ten_series = ten["value"].astype("float64").dropna()
    two_series = two["value"].astype("float64").dropna()
    joined = pd.concat([ten_series.rename("ten"), two_series.rename("two")], axis=1).dropna()
    if joined.empty:
        return insufficient_result(NAME)

    spread = joined["ten"] - joined["two"]
    current = float(spread.iloc[-1])
    signal, short_label = _classify(current)
    recent_inversion = _detect_recent_inversion_change(spread)

    return IndicatorResult(
        name=NAME,
        value=current,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "spread": current,
            "ten_year": float(joined["ten"].iloc[-1]),
            "two_year": float(joined["two"].iloc[-1]),
            "recent_inversion_transition": recent_inversion,
        },
        computed_at=datetime.now(UTC),
    )


def _classify(spread: float) -> tuple[SignalToneLiteral, str]:
    if spread > 0.2:
        return SignalTone.GREEN, f"10Y-2Y 利差 +{spread:.2f}（健康）"
    if spread > 0.0:
        return SignalTone.YELLOW, f"10Y-2Y 利差 +{spread:.2f}（趨平）"
    return SignalTone.RED, f"10Y-2Y 利差 {spread:+.2f}（倒掛）"


def _detect_recent_inversion_change(spread: pd.Series, lookback: int = 20) -> str:
    """Whether spread crossed zero in recent history.

    Returns ``"became_inverted"``, ``"became_normal"``, or ``"none"``.
    """
    tail = spread.tail(lookback + 1)
    if len(tail) < 2:
        return "none"
    prev_sign = tail.iloc[0] > 0
    curr_sign = tail.iloc[-1] > 0
    if prev_sign and not curr_sign:
        return "became_inverted"
    if not prev_sign and curr_sign:
        return "became_normal"
    return "none"

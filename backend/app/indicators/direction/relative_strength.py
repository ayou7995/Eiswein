"""Relative strength vs SPX (C5).

20-day cumulative return of ticker minus 20-day cumulative return of
SPX. Both returns are computed as ``(price_t / price_t-20) - 1``
(strict C5 definition).

Signal table:
* diff >  2% → GREEN  (強於大盤)
* diff < -2% → RED    (弱於大盤)
* else       → YELLOW (接近大盤)
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

NAME = "relative_strength"
_WINDOW = 20
_STRONG_THRESHOLD = 0.02


def compute_relative_strength(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    if frame is None or frame.empty or "close" not in frame.columns:
        return insufficient_result(NAME)
    spx = context.spx_frame
    if spx is None or spx.empty or "close" not in spx.columns:
        return insufficient_result(NAME, detail={"reason": "spx_frame_missing"})
    if len(frame) < _WINDOW + 1 or len(spx) < _WINDOW + 1:
        return insufficient_result(NAME, detail={"bars": len(frame)})

    ticker_return = _cumulative_return(frame["close"])
    spx_return = _cumulative_return(spx["close"])
    if ticker_return is None or spx_return is None:
        return insufficient_result(NAME)

    diff = ticker_return - spx_return
    signal, short_label = _classify(diff)

    return IndicatorResult(
        name=NAME,
        value=diff,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "ticker_20d_return": ticker_return,
            "spx_20d_return": spx_return,
            "diff": diff,
        },
        computed_at=datetime.now(UTC),
    )


def _cumulative_return(close: pd.Series) -> float | None:
    close_f = close.astype("float64").dropna()
    if len(close_f) < _WINDOW + 1:
        return None
    current = float(close_f.iloc[-1])
    prior = float(close_f.iloc[-(_WINDOW + 1)])
    if prior == 0:
        return None
    return (current / prior) - 1.0


def _classify(diff: float) -> tuple[SignalToneLiteral, str]:
    pct = diff * 100.0
    if diff > _STRONG_THRESHOLD:
        return SignalTone.GREEN, f"相對大盤強 {pct:+.1f}%"
    if diff < -_STRONG_THRESHOLD:
        return SignalTone.RED, f"相對大盤弱 {pct:+.1f}%"
    return SignalTone.YELLOW, f"相對大盤持平 {pct:+.1f}%"

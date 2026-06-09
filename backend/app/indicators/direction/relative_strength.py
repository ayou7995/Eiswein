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

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of
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
    # Cross-source: we're only as fresh as the worse-lagged input.
    data_as_of = _min_date(frame_as_of(frame), frame_as_of(spx))
    if len(frame) < _WINDOW + 1 or len(spx) < _WINDOW + 1:
        return insufficient_result(
            NAME, detail={"bars": len(frame)}, data_as_of=data_as_of
        )

    ticker_return = _cumulative_return(frame["close"])
    spx_return = _cumulative_return(spx["close"])
    if ticker_return is None or spx_return is None:
        return insufficient_result(NAME, data_as_of=data_as_of)

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
        data_as_of=data_as_of,
    )


def _min_date(a: date | None, b: date | None) -> date | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


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
    prefix = f"相對大盤 {pct:+.1f}%"
    if diff > _STRONG_THRESHOLD:
        return SignalTone.GREEN, f"{prefix}（強）"
    if diff < -_STRONG_THRESHOLD:
        return SignalTone.RED, f"{prefix}（弱）"
    return SignalTone.YELLOW, f"{prefix}（持平）"

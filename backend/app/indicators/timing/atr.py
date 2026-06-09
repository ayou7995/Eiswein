"""ATR (14) — average true range, normalised as % of price.

ATR is a volatility measurement, not a directional signal. Two roles:

1. **Stop-loss sizing** — ``close - 2 * ATR`` is statistically a better
   stop than a fixed-percentage one because it adapts to each stock's
   own volatility (TSLA's normal day is KO's earnings-day move).
2. **"Is today's move unusual?"** — comparing today's true range to ATR
   tells the operator whether the move is in normal noise or an outlier
   that should change priors.

We surface ATR as a percentage of the latest close so the gauge is
comparable across price levels (1 ATR on $1500 NVDA looks scary in
dollar terms but is normal volatility).

Signal table (driven by ATR% — typical ranges adapted from
``docs/indicators-roadmap.md`` for daily US large-cap):
* ATR%  < 1.5%   → GREEN  (calm, normal volatility)
* 1.5% ≤ ATR% < 3.5%  → YELLOW (elevated, watch position sizing)
* ATR% ≥ 3.5%   → RED    (volatile, tighten stops / shrink size)

Today's TR vs ATR is recorded in ``detail.today_vs_atr`` (ratio) so the
UI can flag a 2-ATR day as "unusual today" without re-deriving it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of, last_float, true_range, wilder_atr
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "atr"
_LENGTH = 14
_MIN_BARS = _LENGTH * 2 + 1

_CALM_THRESHOLD_PCT = 1.5
_ELEVATED_THRESHOLD_PCT = 3.5


def compute_atr(frame: pd.DataFrame, context: IndicatorContext) -> IndicatorResult:
    _ = context
    if frame is None or frame.empty:
        return insufficient_result(NAME)
    required = {"high", "low", "close"}
    if not required.issubset(frame.columns):
        return insufficient_result(NAME)
    data_as_of = frame_as_of(frame)
    if len(frame) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars": len(frame)}, data_as_of=data_as_of
        )

    atr_series = wilder_atr(frame["high"], frame["low"], frame["close"], length=_LENGTH)
    atr_value = last_float(atr_series)
    last_close = last_float(frame["close"])
    if atr_value is None or last_close is None or last_close <= 0:
        return insufficient_result(NAME, data_as_of=data_as_of)

    atr_pct = (atr_value / last_close) * 100.0

    today_tr_series = true_range(frame["high"], frame["low"], frame["close"])
    today_tr = last_float(today_tr_series)
    today_vs_atr = (today_tr / atr_value) if today_tr and atr_value > 0 else None

    signal, short_label = _classify(atr_pct=atr_pct, today_vs_atr=today_vs_atr)

    return IndicatorResult(
        name=NAME,
        value=atr_pct,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "atr": atr_value,
            "atr_pct": atr_pct,
            "close": last_close,
            "today_tr": today_tr,
            "today_vs_atr": today_vs_atr,
            "calm_threshold_pct": _CALM_THRESHOLD_PCT,
            "elevated_threshold_pct": _ELEVATED_THRESHOLD_PCT,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _classify(*, atr_pct: float, today_vs_atr: float | None) -> tuple[SignalToneLiteral, str]:
    """Pick the tone band and short label for the headline.

    ATR isn't bullish/bearish so RED here means "high volatility, size
    down" — not "sell". The UI surfaces this as 「波動偏高」, never as
    a sell instruction."""
    unusual = today_vs_atr is not None and today_vs_atr >= 1.5
    prefix = f"ATR {atr_pct:.1f}%"

    if atr_pct >= _ELEVATED_THRESHOLD_PCT:
        zone = "波動偏高 · 今日異常" if unusual else "波動偏高"
        return SignalTone.RED, f"{prefix}（{zone}）"
    if atr_pct >= _CALM_THRESHOLD_PCT:
        zone = "波動正常偏上 · 今日大震" if unusual else "波動正常偏上"
        return SignalTone.YELLOW, f"{prefix}（{zone}）"
    zone = "波動平靜 · 今日異常震" if unusual else "波動平靜"
    return SignalTone.GREEN, f"{prefix}（{zone}）"

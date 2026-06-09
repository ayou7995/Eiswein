"""HYG/IEF ratio — credit spread risk-on/off (mid-term, votes).

Compares high-yield corporate bonds (HYG) to 7-10Y Treasuries (IEF).
The ratio is a clean credit-spread proxy:

* Rising ratio (HYG outperforming IEF) → **risk-on**, credit market
  healthy. Investors comfortable owning junk-bond risk.
* Falling ratio (IEF outperforming HYG) → **credit stress / risk-off**.
  Money fleeing to safe-haven Treasuries. Historically leads SPX
  selloffs by 7-14 trading days (2008, 2020-03, 2022 Q1, 2023 Mar SVB,
  2023 Oct Israel).

This is a TRUE LEADING indicator vs equity markets — the equity guys
sometimes ignore it for weeks before the index follows. Genuinely
orthogonal information from spx_ma / vix / ad_day, so it earns a vote
in the mid-term posture (extending the table from 4 to 5 indicators).

20-day slope as percent — same threshold semantics as rsp_spy so the
two cross-asset cards read consistently when shown side-by-side.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd

from app.indicators._helpers import frame_as_of
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

NAME = "hyg_ief"

_LOOKBACK = 20
_MIN_BARS = _LOOKBACK + 5
# ±0.05 % per day = ±1 % over 20 trading days. Matches RSP/SPY.
_SLOPE_GREEN_PCT_PER_DAY = 0.05
_SLOPE_RED_PCT_PER_DAY = -0.05


def compute_hyg_ief(_frame: object, context: IndicatorContext) -> IndicatorResult:
    hyg = context.hyg_frame
    ief = context.ief_frame
    if hyg is None or hyg.empty or "close" not in hyg.columns:
        return insufficient_result(NAME)
    if ief is None or ief.empty or "close" not in ief.columns:
        return insufficient_result(NAME)

    data_as_of = _min_date(frame_as_of(hyg), frame_as_of(ief))

    if len(hyg) < _MIN_BARS or len(ief) < _MIN_BARS:
        return insufficient_result(
            NAME,
            detail={"bars_hyg": len(hyg), "bars_ief": len(ief)},
            data_as_of=data_as_of,
        )

    joined = pd.concat(
        [hyg["close"].rename("hyg"), ief["close"].rename("ief")], axis=1
    ).dropna()
    if len(joined) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars_joined": len(joined)}, data_as_of=data_as_of
        )

    ratio = joined["hyg"] / joined["ief"]
    current_ratio = float(ratio.iloc[-1])
    tail = ratio.iloc[-_LOOKBACK:]
    slope_pct_per_day = _percent_slope_per_day(tail)
    slope_20d_pct = slope_pct_per_day * _LOOKBACK

    signal, short_label = _classify(
        slope_pct_per_day=slope_pct_per_day, slope_20d_pct=slope_20d_pct
    )

    return IndicatorResult(
        name=NAME,
        value=current_ratio,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "ratio": current_ratio,
            "hyg_close": float(joined["hyg"].iloc[-1]),
            "ief_close": float(joined["ief"].iloc[-1]),
            "slope_pct_per_day": slope_pct_per_day,
            "slope_20d_pct": slope_20d_pct,
            "lookback_days": _LOOKBACK,
        },
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _percent_slope_per_day(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    first = float(series.iloc[0])
    last = float(series.iloc[-1])
    if first == 0:
        return 0.0
    total_pct = (last - first) / first * 100.0
    return total_pct / len(series)


def _classify(
    *, slope_pct_per_day: float, slope_20d_pct: float
) -> tuple[SignalToneLiteral, str]:
    suffix = f"HYG/IEF 20D {slope_20d_pct:+.2f}%"
    if slope_pct_per_day >= _SLOPE_GREEN_PCT_PER_DAY:
        return SignalTone.GREEN, f"{suffix}（信用偏好）"
    if slope_pct_per_day <= _SLOPE_RED_PCT_PER_DAY:
        return SignalTone.RED, f"{suffix}（信用利差擴大）"
    return SignalTone.YELLOW, f"{suffix}（信用利差持平）"


def _min_date(a: date | None, b: date | None) -> date | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


__all__ = ["NAME", "compute_hyg_ief"]

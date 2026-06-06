"""Watchlist Cumulative A/D Line — breadth + SPX divergence (v2 Phase 4).

The canonical NYSE A/D Line tracks ``cumsum(advances - declines)`` over
the broad market. Where SPX makes new highs but the A/D Line does NOT,
the rally is "narrow" — fewer constituents participating. That negative
divergence has historically preceded most multi-week corrections.

We adapt the concept to Eiswein's personal-tool scope: the breadth
universe is the operator's *own watchlist* rather than the 5000-stock
NYSE universe. This is more informative for a personal portfolio
("are MY tracked names accumulating?") and ships without any new data
source — we already have daily_price for every watchlist symbol.

The breadth time series is pre-computed in ``build_context`` and lives
on ``IndicatorContext.watchlist_breadth`` so this indicator stays a
pure read.

Signal rules (last 20 trading bars):

* **GREEN** — AD Line slope > 0 AND SPX slope > 0 (broad rally — most
  watchlist names participating in the SPX uptrend).
* **RED**   — SPX slope > 0 AND AD Line slope ≤ 0 (negative divergence:
  index up but breadth weakening — only mega-caps carrying).
* **YELLOW** otherwise (down market, sideways, or both up but breadth
  ambiguous).
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

NAME = "ad_line"

_LOOKBACK = 20
_MIN_BARS = _LOOKBACK + 5


def compute_ad_line(_frame: object, context: IndicatorContext) -> IndicatorResult:
    breadth = context.watchlist_breadth
    spx = context.spx_frame
    if breadth is None or breadth.empty:
        return insufficient_result(NAME)
    if spx is None or spx.empty or "close" not in spx.columns:
        return insufficient_result(NAME)
    # Cross-source min: breadth and SPY can lag independently — we're
    # only as fresh as whichever finished updating later.
    data_as_of = _min_date(frame_as_of(breadth), frame_as_of(spx))
    if len(breadth) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars": len(breadth)}, data_as_of=data_as_of
        )

    ad_line = breadth["ad_line"]
    ad_slope = _normalized_slope(ad_line.iloc[-_LOOKBACK:])
    spx_close = spx["close"].astype("float64")
    spx_slope = _normalized_slope(spx_close.iloc[-_LOOKBACK:])
    if ad_slope is None or spx_slope is None:
        return insufficient_result(NAME, data_as_of=data_as_of)

    current_advances = int(breadth["advances"].iloc[-1])
    current_declines = int(breadth["declines"].iloc[-1])
    current_net = int(breadth["net"].iloc[-1])
    current_ad = float(ad_line.iloc[-1])

    signal, short_label = _classify(ad_slope=ad_slope, spx_slope=spx_slope)

    return IndicatorResult(
        name=NAME,
        value=current_ad,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "advances": current_advances,
            "declines": current_declines,
            "net": current_net,
            "ad_line": current_ad,
            "ad_slope_20d": ad_slope,
            "spx_slope_20d": spx_slope,
            "divergence": signal == SignalTone.RED,
            "lookback": _LOOKBACK,
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


def _normalized_slope(series: pd.Series) -> float | None:
    """Return slope of ``series`` (per bar) normalised by the abs of its
    starting value so SPX (in dollars) and AD Line (in raw integer count)
    yield comparable magnitudes."""
    cleaned = series.dropna()
    if len(cleaned) < 2:
        return None
    first = float(cleaned.iloc[0])
    last = float(cleaned.iloc[-1])
    base = abs(first) if abs(first) > 0 else 1.0
    return (last - first) / len(cleaned) / base


def _classify(*, ad_slope: float, spx_slope: float) -> tuple[SignalToneLiteral, str]:
    if ad_slope > 0 and spx_slope > 0:
        return (
            SignalTone.GREEN,
            "廣度與大盤同步上升",
        )
    if spx_slope > 0 and ad_slope <= 0:
        return (
            SignalTone.RED,
            "負背離:大盤上但廣度下",
        )
    return (
        SignalTone.YELLOW,
        "廣度與大盤同步下/盤整",
    )


__all__ = ["NAME", "compute_ad_line"]

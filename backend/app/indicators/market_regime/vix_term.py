"""VIX Term Structure — short-vs-3M VIX ratio (v2 Phase 4).

A standalone read of the VIX futures-curve shape is unavailable on
FRED, but its proxy — the spot VIX vs the CBOE 3-Month VIX Index —
captures the same insight:

* ``ratio = VIX / VIX3M < 0.95``  → deep contango, market calm.
  Front-month fear is meaningfully cheaper than 3-month forward fear.
  Historically associated with risk-on regimes. **GREEN**.
* ``0.95 ≤ ratio < 1.0``           → mild contango, normal.
  The default state. **YELLOW**.
* ``ratio ≥ 1.0``                  → backwardation / inverted curve.
  Spot fear ≥ 3-month forward fear means the market is pricing
  *immediate* stress higher than longer-dated expectations — a textbook
  panic signal. **RED**.

This is what professional vol traders watch alongside the absolute VIX
level. Useful as a short-term market-posture vote that catches stress
the spot-VIX-level threshold can miss (VIX 22 can be either a normal
day or the start of a vol cascade — the curve shape disambiguates).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.indicators._helpers import frame_as_of, last_float
from app.indicators.base import (
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
    insufficient_result,
)

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

NAME = "vix_term"

_CONTANGO_THRESHOLD = 0.95
_INVERSION_THRESHOLD = 1.0
_MIN_BARS = 5


def compute_vix_term(_frame: object, context: IndicatorContext) -> IndicatorResult:
    """Compute the VIX/VIX3M ratio + classify.

    Reads ``VIXCLS`` and ``VXVCLS`` from the shared macro frames. Both
    are FRED daily series with a single ``value`` column.
    """
    vix_frame: pd.DataFrame | None = context.macro_frames.get("VIXCLS")
    vix3m_frame: pd.DataFrame | None = context.macro_frames.get("VXVCLS")
    if vix_frame is None or vix3m_frame is None:
        return insufficient_result(NAME)
    if vix_frame.empty or vix3m_frame.empty:
        return insufficient_result(NAME)
    if "value" not in vix_frame.columns or "value" not in vix3m_frame.columns:
        return insufficient_result(NAME)
    # Cross-source min: as-of date is whichever FRED series last published.
    data_as_of = _min_date(frame_as_of(vix_frame), frame_as_of(vix3m_frame))
    if len(vix_frame) < _MIN_BARS or len(vix3m_frame) < _MIN_BARS:
        return insufficient_result(
            NAME, detail={"bars_vix": len(vix_frame)}, data_as_of=data_as_of
        )

    vix_value = last_float(vix_frame["value"])
    vix3m_value = last_float(vix3m_frame["value"])
    if vix_value is None or vix3m_value is None or vix3m_value <= 0:
        return insufficient_result(NAME, data_as_of=data_as_of)

    ratio = vix_value / vix3m_value
    signal, short_label = _classify(ratio=ratio, vix=vix_value, vix3m=vix3m_value)

    return IndicatorResult(
        name=NAME,
        value=ratio,
        signal=signal,
        data_sufficient=True,
        short_label=short_label,
        detail={
            "vix": vix_value,
            "vix3m": vix3m_value,
            "ratio": ratio,
            "contango_threshold": _CONTANGO_THRESHOLD,
            "inversion_threshold": _INVERSION_THRESHOLD,
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


def _classify(*, ratio: float, vix: float, vix3m: float) -> tuple[SignalToneLiteral, str]:
    if ratio >= _INVERSION_THRESHOLD:
        return (
            SignalTone.RED,
            f"倒掛 (VIX {vix:.1f} ≥ VIX3M {vix3m:.1f})",
        )
    if ratio < _CONTANGO_THRESHOLD:
        return (
            SignalTone.GREEN,
            f"深度 contango (比 {ratio:.2f})",
        )
    return (
        SignalTone.YELLOW,
        f"接近平坦 (比 {ratio:.2f})",
    )


__all__ = ["NAME", "compute_vix_term"]

"""CBOE SKEW Index — short-term tail-risk vote."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.skew import compute_skew


def _skew_frame(levels: np.ndarray, *, start: str = "2026-01-01") -> pd.DataFrame:
    n = len(levels)
    idx = pd.date_range(start, periods=n, freq="B")
    close = pd.Series(levels, index=idx, dtype="float64")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 0,
        },
        index=idx,
    )


def _ctx(skew: pd.DataFrame | None) -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 5), skew_frame=skew)


def test_skew_insufficient_when_missing() -> None:
    assert compute_skew(None, _ctx(None)).data_sufficient is False


def test_skew_insufficient_when_too_few_bars() -> None:
    result = compute_skew(None, _ctx(_skew_frame(np.full(5, 120.0))))
    assert result.data_sufficient is False


def test_skew_normal_level_is_green() -> None:
    # Stable around 120 → below 130 normal threshold → GREEN.
    result = compute_skew(None, _ctx(_skew_frame(np.full(30, 120.0))))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "尾部風險低" in result.short_label


def test_skew_elevated_level_is_yellow() -> None:
    # Settles at 138 → between 130 and 145 → YELLOW.
    result = compute_skew(None, _ctx(_skew_frame(np.full(30, 138.0))))
    assert result.signal == SignalTone.YELLOW
    assert "尾部風險上升" in result.short_label


def test_skew_high_level_is_red() -> None:
    # 150 ≥ 145 elevated threshold → RED.
    result = compute_skew(None, _ctx(_skew_frame(np.full(30, 150.0))))
    assert result.signal == SignalTone.RED
    assert "機構避險" in result.short_label


def test_skew_detail_keys_present() -> None:
    result = compute_skew(None, _ctx(_skew_frame(np.full(30, 125.0))))
    keys = {
        "level",
        "ten_day_change",
        "trend",
        "percentile_1y",
        "threshold_normal_high",
        "threshold_elevated_high",
    }
    assert keys.issubset(result.detail.keys())


def test_skew_propagates_data_as_of() -> None:
    frame = _skew_frame(np.full(30, 120.0), start="2026-04-01")
    result = compute_skew(None, _ctx(frame))
    assert result.data_as_of == frame.index[-1].date()

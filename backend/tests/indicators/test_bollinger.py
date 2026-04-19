"""Bollinger Bands (20, 2σ) tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.timing.bollinger import compute_bollinger


def _build(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range(
        datetime(2024, 1, 2),
        periods=len(closes),
        freq="B",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def test_price_above_upper_band_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 20 flat bars then a big spike breaks the upper band.
    closes = [100.0] * 20 + [108.0]
    frame = _build(closes)
    ctx = indicator_context_factory()
    result = compute_bollinger(frame, ctx)
    assert result.data_sufficient is True
    # σ is 0 in the flat portion → upper/middle/lower all equal 100;
    # anything above is RED.
    assert result.signal == "red"


def test_price_below_lower_band_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    closes = [100.0] * 20 + [92.0]
    frame = _build(closes)
    ctx = indicator_context_factory()
    result = compute_bollinger(frame, ctx)
    assert result.signal == "green"


def test_short_frame_is_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = _build([100.0] * 10)
    ctx = indicator_context_factory()
    result = compute_bollinger(frame, ctx)
    assert result.data_sufficient is False


def test_detail_has_band_fields(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_bollinger(trend_frame, ctx)
    for k in ("upper", "middle", "lower", "position"):
        assert k in result.detail

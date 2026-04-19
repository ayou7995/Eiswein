"""RSI(14) daily + weekly tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.direction.rsi import compute_rsi


def _make_close(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range(
        datetime(2023, 1, 2),
        periods=len(values),
        freq="B",
        tz="America/New_York",
    )
    return pd.DataFrame({"close": values, "open": values, "high": values, "low": values,
                         "volume": [1_000_000] * len(values)}, index=idx)


def test_rsi_flat_series_is_around_50(
    flat_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_rsi(flat_frame, ctx)
    assert result.data_sufficient is True
    assert result.value is not None
    assert 45.0 <= result.value <= 55.0


def test_rsi_monotonic_uptrend_is_overbought(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 200 monotonic up bars → RSI saturates near 100 → daily + weekly both > 70 → RED.
    frame = _make_close([100.0 + i for i in range(200)])
    ctx = indicator_context_factory()
    result = compute_rsi(frame, ctx)
    assert result.value is not None
    assert result.value > 70.0
    assert result.signal == "red"


def test_rsi_insufficient_data(
    short_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_rsi(short_frame, ctx)
    assert result.data_sufficient is False


def test_rsi_short_label_contains_rsi(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_rsi(trend_frame, ctx)
    assert "RSI" in result.short_label


def test_rsi_handles_nan_in_close(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = trend_frame.copy()
    frame.loc[frame.index[5], "close"] = float("nan")
    ctx = indicator_context_factory()
    result = compute_rsi(frame, ctx)
    # Single NaN propagates one bar but overall frame is long enough.
    assert result.data_sufficient is True

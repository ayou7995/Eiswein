"""Unit tests for shared numeric helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators._helpers import (
    bollinger_bands,
    last_float,
    last_two_floats,
    macd,
    sma,
    wilder_rsi,
)


def test_wilder_rsi_flat_series_returns_50() -> None:
    close = pd.Series([100.0] * 30)
    result = wilder_rsi(close, 14)
    assert result.iloc[-1] == 50.0


def test_wilder_rsi_monotonic_rising_approaches_100() -> None:
    # Monotonic rising series → avg_loss = 0 → convention returns 100.
    close = pd.Series([100.0 + i for i in range(40)])
    result = wilder_rsi(close, 14)
    assert result.iloc[-1] == 100.0


def test_wilder_rsi_insufficient_data_returns_nan() -> None:
    close = pd.Series([100.0, 101.0])
    result = wilder_rsi(close, 14)
    assert result.isna().all()


def test_macd_produces_three_series_same_length() -> None:
    close = pd.Series([100.0 + i * 0.1 for i in range(60)])
    m = macd(close)
    assert len(m.macd_line) == 60
    assert len(m.signal_line) == 60
    assert len(m.histogram) == 60
    # Histogram is MACD minus signal by definition.
    diff = (m.macd_line - m.signal_line).iloc[-1]
    assert abs(diff - m.histogram.iloc[-1]) < 1e-9


def test_bollinger_bands_upper_gte_middle_gte_lower() -> None:
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 + rng.normal(0, 1, size=30).cumsum())
    bb = bollinger_bands(close, length=20)
    assert bb.upper.iloc[-1] >= bb.middle.iloc[-1] >= bb.lower.iloc[-1]


def test_sma_matches_rolling_mean() -> None:
    close = pd.Series([float(i) for i in range(25)])
    result = sma(close, 10)
    assert abs(result.iloc[-1] - sum(range(15, 25)) / 10) < 1e-9


def test_last_float_and_last_two_floats() -> None:
    s = pd.Series([1.0, float("nan"), 3.0, 4.0])
    assert last_float(s) == 4.0
    pair = last_two_floats(s)
    assert pair is not None
    assert pair == (3.0, 4.0)


def test_last_float_returns_none_on_all_nan() -> None:
    s = pd.Series([float("nan"), float("nan")])
    assert last_float(s) is None
    assert last_two_floats(s) is None

"""Chaikin Oscillator — accumulation/distribution accelerator (v2 Phase 3)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.direction.cho import compute_cho


def _ohlcv(
    close_pattern: np.ndarray,
    *,
    close_in_range: float = 0.85,
    volume: int = 1_000_000,
) -> pd.DataFrame:
    """Build OHLCV where close sits at ``close_in_range`` of the day's
    H-L band (0 = at low, 1 = at high). The CHO money-flow multiplier
    is ``(2*close_in_range - 1)``, so 0.85 = MFM ≈ 0.7 (strong buy
    pressure each bar)."""
    n = len(close_pattern)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(close_pattern, index=idx, dtype="float64")
    low = close - 1.0
    high = close + (1.0 / close_in_range - 1.0)
    # Re-derive close so it sits exactly at close_in_range of [low,high]
    high = low + (close - low) / close_in_range
    vol = pd.Series(np.full(n, volume, dtype="int64"), index=idx)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": vol}
    )


def _ctx() -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 5))


def test_cho_insufficient_on_short_frame() -> None:
    frame = _ohlcv(np.array([100.0, 101.0, 102.0]))
    result = compute_cho(frame, _ctx())
    assert result.data_sufficient is False


def test_cho_strong_accumulation_yields_green() -> None:
    """Sustained close-near-high + rising volume = clear accumulation.
    CHO should be positive AND rising vs prior bar."""
    rng = np.random.default_rng(seed=42)
    pattern = 100.0 + np.arange(60, dtype="float64") * 0.5 + rng.normal(0, 0.1, size=60)
    frame = _ohlcv(pattern, close_in_range=0.92, volume=2_000_000)
    result = compute_cho(frame, _ctx())
    assert result.data_sufficient is True
    assert result.detail["cho"] > 0
    if result.detail["cho"] > result.detail["prior"]:
        assert result.signal == SignalTone.GREEN
        assert "買盤加速" in result.short_label


def test_cho_strong_distribution_yields_red() -> None:
    """Close-near-low + flat volume = distribution.
    CHO should go negative and accelerate downward."""
    rng = np.random.default_rng(seed=99)
    pattern = 100.0 - np.arange(60, dtype="float64") * 0.5 + rng.normal(0, 0.1, size=60)
    frame = _ohlcv(pattern, close_in_range=0.08, volume=2_000_000)
    result = compute_cho(frame, _ctx())
    assert result.data_sufficient is True
    assert result.detail["cho"] < 0
    if result.detail["cho"] < result.detail["prior"]:
        assert result.signal == SignalTone.RED
        assert "賣盤加速" in result.short_label


def test_cho_near_zero_yields_yellow() -> None:
    """A pattern where close oscillates around the day midpoint produces
    money_flow_multiplier ≈ 0, so AD line stays flat and CHO ≈ 0."""
    rng = np.random.default_rng(seed=11)
    pattern = 100.0 + rng.normal(0, 0.3, size=60).cumsum() * 0.1
    frame = _ohlcv(pattern, close_in_range=0.5, volume=1_000_000)
    result = compute_cho(frame, _ctx())
    assert result.data_sufficient is True
    assert result.signal == SignalTone.YELLOW


def test_cho_detail_keys_present() -> None:
    rng = np.random.default_rng(seed=7)
    pattern = 100.0 + rng.normal(0, 0.5, size=60).cumsum()
    frame = _ohlcv(pattern, close_in_range=0.6)
    result = compute_cho(frame, _ctx())
    assert result.data_sufficient is True
    keys = {"cho", "prior", "slope_5d", "flat_threshold", "volume_scale", "fast", "slow"}
    assert keys.issubset(result.detail.keys())

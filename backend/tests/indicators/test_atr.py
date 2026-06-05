"""ATR — per-stock volatility scale (v2 Phase 2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.timing.atr import compute_atr


def _ohlcv(close: np.ndarray, *, range_pct: float = 0.01) -> pd.DataFrame:
    """OHLCV synthetic frame where the H-L range is a fixed % of close."""
    n = len(close)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close_s = pd.Series(close, index=idx, dtype="float64")
    half_range = close_s * (range_pct / 2)
    high = close_s + half_range
    low = close_s - half_range
    volume = pd.Series(np.full(n, 1_000_000, dtype="int64"), index=idx)
    return pd.DataFrame(
        {"open": close_s, "high": high, "low": low, "close": close_s, "volume": volume}
    )


def _ctx() -> IndicatorContext:
    from datetime import date

    return IndicatorContext(today=date(2026, 6, 5))


def test_atr_returns_insufficient_when_frame_too_short() -> None:
    frame = _ohlcv(np.full(10, 100.0))
    result = compute_atr(frame, _ctx())
    assert result.data_sufficient is False


def test_atr_emits_pct_value_and_green_on_low_volatility() -> None:
    """1% daily range → ATR% ≈ 1% → GREEN ('calm')."""
    closes = np.array([100.0 + 0.1 * i for i in range(50)])
    result = compute_atr(_ohlcv(closes, range_pct=0.01), _ctx())
    assert result.data_sufficient is True
    assert result.signal == "green"
    assert 0.5 < result.detail["atr_pct"] < 1.5


def test_atr_yellow_when_volatility_elevated() -> None:
    """~2.5% daily range → ATR% in [1.5, 3.5) → YELLOW."""
    closes = np.array([100.0 + 0.1 * i for i in range(50)])
    result = compute_atr(_ohlcv(closes, range_pct=0.025), _ctx())
    assert result.data_sufficient is True
    assert result.signal == "yellow"


def test_atr_red_when_volatility_very_high() -> None:
    """4% daily range → ATR% ≥ 3.5% → RED ('high vol')."""
    closes = np.array([100.0 + 0.1 * i for i in range(50)])
    result = compute_atr(_ohlcv(closes, range_pct=0.04), _ctx())
    assert result.data_sufficient is True
    assert result.signal == "red"


def test_atr_detail_carries_today_vs_atr_ratio() -> None:
    """The 'is today's move unusual?' flag is the ratio of today's TR
    to the smoothed ATR. UI uses this to flag 2-ATR days as 異常."""
    closes = np.array([100.0 + 0.1 * i for i in range(50)])
    result = compute_atr(_ohlcv(closes, range_pct=0.01), _ctx())
    assert "today_vs_atr" in result.detail
    assert "calm_threshold_pct" in result.detail
    assert "elevated_threshold_pct" in result.detail

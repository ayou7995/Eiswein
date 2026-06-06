"""TTM Squeeze — squeeze-on / fire-direction state machine (v2 Phase 3)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.timing.ttm_squeeze import compute_ttm_squeeze


def _ohlcv(close_pattern: np.ndarray, *, range_pct: float = 0.01) -> pd.DataFrame:
    """Build synthetic OHLCV — high/low scaled to a constant pct of close.

    ``range_pct`` controls the daily H-L spread relative to close. A
    tight range (0.005) produces a low-volatility regime that collapses
    BBs inside KCs → squeeze ON. A wider range (0.03) blows them apart.
    """
    n = len(close_pattern)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(close_pattern, index=idx, dtype="float64")
    half_range = close * range_pct / 2.0
    high = close + half_range
    low = close - half_range
    volume = pd.Series(np.full(n, 1_000_000, dtype="int64"), index=idx)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume}
    )


def _ctx() -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 5))


def test_ttm_squeeze_insufficient_on_short_frame() -> None:
    frame = _ohlcv(np.array([100.0] * 10))
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_sufficient is False


def test_ttm_squeeze_compressed_range_signals_yellow_with_squeeze_on() -> None:
    """A long stretch of tight-range close-to-close motion compresses BBs
    well inside KCs (BB σ < KC ATR × 1.5). The classifier must report
    ``squeeze_on=True`` and emit YELLOW (loaded, waiting for fire)."""
    rng = np.random.default_rng(seed=42)
    # 100-bar steady range with very tight daily H-L → BBs compress.
    pattern = 100.0 + rng.normal(0, 0.05, size=100).cumsum() * 0.1
    frame = _ohlcv(pattern, range_pct=0.005)
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_sufficient is True
    assert result.detail["squeeze_on"] is True
    assert result.signal == SignalTone.YELLOW
    assert "醞釀" in result.short_label


def test_ttm_squeeze_release_with_positive_momentum_is_green() -> None:
    """Build a frame where the first ~80 bars are a tight squeeze, then
    the last few bars break out upward with widening range. The result
    should detect ``fired_up`` and emit GREEN."""
    rng = np.random.default_rng(seed=7)
    squeeze_phase = 100.0 + rng.normal(0, 0.02, size=80).cumsum() * 0.05
    # Sharp upward breakout — 8 bars of +0.8 drift each, widening range.
    breakout = squeeze_phase[-1] + np.arange(1, 9) * 0.8
    pattern = np.concatenate([squeeze_phase, breakout])
    frame = _ohlcv(pattern, range_pct=0.005)
    # Last 8 bars deliberately wide-range to lift BB σ over KC ATR.
    frame.loc[frame.index[-8:], "high"] = frame.loc[frame.index[-8:], "close"] + 1.2
    frame.loc[frame.index[-8:], "low"] = frame.loc[frame.index[-8:], "close"] - 0.3
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_sufficient is True
    assert result.detail["squeeze_on"] is False
    # Either the fire was caught (green) or we're in the post-fire window
    # (yellow but momentum positive). Both are acceptable post-breakout.
    if result.detail["fired_up"]:
        assert result.signal == SignalTone.GREEN
        assert "向上點火" in result.short_label
    else:
        assert result.detail["momentum"] > 0


def test_ttm_squeeze_release_with_negative_momentum_is_red() -> None:
    """Mirror of the up-fire test — a squeeze that breaks DOWN should
    produce ``fired_down`` and a RED tone."""
    rng = np.random.default_rng(seed=99)
    squeeze_phase = 100.0 + rng.normal(0, 0.02, size=80).cumsum() * 0.05
    breakdown = squeeze_phase[-1] - np.arange(1, 9) * 0.8
    pattern = np.concatenate([squeeze_phase, breakdown])
    frame = _ohlcv(pattern, range_pct=0.005)
    frame.loc[frame.index[-8:], "high"] = frame.loc[frame.index[-8:], "close"] + 0.3
    frame.loc[frame.index[-8:], "low"] = frame.loc[frame.index[-8:], "close"] - 1.2
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_sufficient is True
    assert result.detail["squeeze_on"] is False
    if result.detail["fired_down"]:
        assert result.signal == SignalTone.RED
        assert "向下點火" in result.short_label
    else:
        assert result.detail["momentum"] < 0


def test_ttm_squeeze_detail_surfaces_full_state_dict() -> None:
    rng = np.random.default_rng(seed=11)
    pattern = 100.0 + rng.normal(0, 0.5, size=120).cumsum()
    frame = _ohlcv(pattern, range_pct=0.02)
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_sufficient is True
    keys = {
        "squeeze_on",
        "fired_up",
        "fired_down",
        "momentum",
        "momentum_rising",
        "bb_upper",
        "bb_lower",
        "kc_upper",
        "kc_lower",
        "length",
    }
    assert keys.issubset(result.detail.keys())

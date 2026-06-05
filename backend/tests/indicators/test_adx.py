"""ADX / SPX ADX — trend strength classifier (v2 Phase 2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.market_regime.spx_adx import compute_spx_adx
from app.indicators.timing.adx import compute_adx


def _ohlcv(close_pattern: np.ndarray) -> pd.DataFrame:
    """Build a synthetic OHLCV frame from a close-price array.

    High = close + small noise; low = close - small noise; volume
    constant. Sufficient detail for ADX which only reads H/L/C."""
    n = len(close_pattern)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(close_pattern, index=idx, dtype="float64")
    high = close + 0.5
    low = close - 0.5
    volume = pd.Series(np.full(n, 1_000_000, dtype="int64"), index=idx)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume})


def _ctx(spx_frame: pd.DataFrame | None = None) -> IndicatorContext:
    from datetime import date

    return IndicatorContext(today=date(2026, 6, 5), spx_frame=spx_frame)


def test_adx_returns_insufficient_on_short_frame() -> None:
    frame = _ohlcv(np.array([100.0] * 5))
    result = compute_adx(frame, _ctx())
    assert result.data_sufficient is False


def test_adx_classifies_strong_uptrend_as_green() -> None:
    """A clean monotonic rise should produce ADX ≥ 25 and a GREEN tone."""
    # 60 bars rising 0.5/day = strong directional trend → high ADX.
    closes = np.array([100.0 + 0.5 * i for i in range(60)])
    result = compute_adx(_ohlcv(closes), _ctx())
    assert result.data_sufficient is True
    assert result.signal == "green"
    assert result.detail["adx"] >= 25
    assert result.detail["direction"] == "up"


def test_adx_classifies_choppy_market_as_yellow() -> None:
    """Sideways oscillation should have low ADX → YELLOW."""
    closes = np.array([100.0 + 0.5 * np.sin(i / 2) for i in range(60)])
    result = compute_adx(_ohlcv(closes), _ctx())
    assert result.data_sufficient is True
    assert result.signal == "yellow"
    assert result.detail["adx"] < 25


def test_adx_detail_carries_di_lines_and_thresholds() -> None:
    """``detail`` must surface +DI / -DI / thresholds so the UI can
    render the full diagnostic without re-deriving them."""
    closes = np.array([100.0 + 0.3 * i for i in range(50)])
    result = compute_adx(_ohlcv(closes), _ctx())
    assert {"adx", "plus_di", "minus_di", "direction", "slope_5d"} <= result.detail.keys()
    assert result.detail["trend_threshold"] == 25.0


def test_spx_adx_reads_from_context_spx_frame() -> None:
    closes = np.array([4500.0 + 5.0 * i for i in range(60)])
    spx = _ohlcv(closes)
    # Pass an empty frame as the orchestrator does; spx_adx must read
    # from ``context.spx_frame`` instead.
    result = compute_spx_adx(pd.DataFrame(), _ctx(spx_frame=spx))
    assert result.data_sufficient is True
    assert result.signal == "green"


def test_spx_adx_returns_insufficient_when_context_lacks_spx() -> None:
    result = compute_spx_adx(pd.DataFrame(), _ctx(spx_frame=None))
    assert result.data_sufficient is False

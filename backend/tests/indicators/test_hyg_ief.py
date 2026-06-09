"""HYG/IEF ratio — credit spread risk-on/off (mid-term, votes)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.hyg_ief import compute_hyg_ief


def _ohlc(close_pattern: np.ndarray, *, start: str = "2026-01-01") -> pd.DataFrame:
    n = len(close_pattern)
    idx = pd.date_range(start, periods=n, freq="B")
    close = pd.Series(close_pattern, index=idx, dtype="float64")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000_000,
        },
        index=idx,
    )


def _ctx(hyg: pd.DataFrame | None, ief: pd.DataFrame | None) -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 5), hyg_frame=hyg, ief_frame=ief)


def test_hyg_ief_insufficient_when_either_missing() -> None:
    assert compute_hyg_ief(None, _ctx(None, None)).data_sufficient is False
    hyg = _ohlc(np.full(40, 80.0))
    assert compute_hyg_ief(None, _ctx(hyg, None)).data_sufficient is False
    assert compute_hyg_ief(None, _ctx(None, hyg)).data_sufficient is False


def test_hyg_ief_credit_risk_on_is_green() -> None:
    """HYG outperforming IEF → ratio rising → GREEN (risk-on)."""
    hyg = _ohlc(80.0 + np.arange(40, dtype="float64") * 0.1)
    ief = _ohlc(np.full(40, 95.0))
    result = compute_hyg_ief(None, _ctx(hyg, ief))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "信用偏好" in result.short_label


def test_hyg_ief_credit_stress_is_red() -> None:
    """IEF outperforming HYG → ratio falling → RED (credit stress)."""
    hyg = _ohlc(np.full(40, 80.0))
    ief = _ohlc(95.0 + np.arange(40, dtype="float64") * 0.1)
    result = compute_hyg_ief(None, _ctx(hyg, ief))
    assert result.signal == SignalTone.RED
    assert "信用利差擴大" in result.short_label


def test_hyg_ief_flat_ratio_is_yellow() -> None:
    hyg = _ohlc(80.0 * (1.0 + np.arange(40, dtype="float64") * 0.001))
    ief = _ohlc(95.0 * (1.0 + np.arange(40, dtype="float64") * 0.001))
    result = compute_hyg_ief(None, _ctx(hyg, ief))
    assert result.signal == SignalTone.YELLOW


def test_hyg_ief_detail_keys_present() -> None:
    hyg = _ohlc(80.0 + np.arange(40, dtype="float64") * 0.1)
    ief = _ohlc(np.full(40, 95.0))
    result = compute_hyg_ief(None, _ctx(hyg, ief))
    keys = {"ratio", "hyg_close", "ief_close", "slope_pct_per_day", "slope_20d_pct"}
    assert keys.issubset(result.detail.keys())


def test_hyg_ief_propagates_cross_source_min_date() -> None:
    hyg = _ohlc(80.0 + np.arange(40, dtype="float64") * 0.1, start="2026-04-01")
    ief = _ohlc(np.full(35, 95.0), start="2026-04-01")
    result = compute_hyg_ief(None, _ctx(hyg, ief))
    assert result.data_as_of == ief.index[-1].date()

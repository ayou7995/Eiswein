"""RSP/SPY ratio — equal-weight vs cap-weight breadth (mid-term)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.rsp_spy import compute_rsp_spy


def _ohlc(close_pattern: np.ndarray, *, start: str = "2026-01-01") -> pd.DataFrame:
    n = len(close_pattern)
    idx = pd.date_range(start, periods=n, freq="B")
    close = pd.Series(close_pattern, index=idx, dtype="float64")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000,
        },
        index=idx,
    )


def _ctx(spy: pd.DataFrame | None, rsp: pd.DataFrame | None) -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 5), spx_frame=spy, rsp_frame=rsp)


def test_rsp_spy_insufficient_when_either_missing() -> None:
    assert compute_rsp_spy(None, _ctx(None, None)).data_sufficient is False
    spy = _ohlc(np.full(40, 400.0))
    assert compute_rsp_spy(None, _ctx(spy, None)).data_sufficient is False
    assert compute_rsp_spy(None, _ctx(None, spy)).data_sufficient is False


def test_rsp_spy_broad_rally_is_green() -> None:
    """RSP rising faster than SPY → ratio rising → GREEN."""
    spy = _ohlc(400.0 + np.arange(40, dtype="float64") * 0.5)  # +0.5/day
    rsp = _ohlc(200.0 + np.arange(40, dtype="float64") * 0.7)  # +0.7/day (faster %)
    result = compute_rsp_spy(None, _ctx(spy, rsp))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "廣度健康" in result.short_label


def test_rsp_spy_narrow_rally_is_red() -> None:
    """SPY rising while RSP flat → ratio falling → RED (Mag-7 carrying)."""
    spy = _ohlc(400.0 + np.arange(40, dtype="float64") * 0.5)
    rsp = _ohlc(np.full(40, 200.0))  # flat
    result = compute_rsp_spy(None, _ctx(spy, rsp))
    assert result.signal == SignalTone.RED
    assert "窄漲警示" in result.short_label


def test_rsp_spy_flat_ratio_is_yellow() -> None:
    """Both rising at same pct rate → ratio constant → YELLOW."""
    spy = _ohlc(400.0 * (1.0 + np.arange(40, dtype="float64") * 0.001))
    rsp = _ohlc(200.0 * (1.0 + np.arange(40, dtype="float64") * 0.001))
    result = compute_rsp_spy(None, _ctx(spy, rsp))
    assert result.signal == SignalTone.YELLOW


def test_rsp_spy_detail_keys_present() -> None:
    spy = _ohlc(400.0 + np.arange(40, dtype="float64") * 0.5)
    rsp = _ohlc(200.0 + np.arange(40, dtype="float64") * 0.7)
    result = compute_rsp_spy(None, _ctx(spy, rsp))
    keys = {"ratio", "rsp_close", "spy_close", "slope_pct_per_day", "slope_20d_pct"}
    assert keys.issubset(result.detail.keys())


def test_rsp_spy_propagates_cross_source_min_date() -> None:
    """data_as_of = min(spy.last, rsp.last) — only as fresh as worst input."""
    spy = _ohlc(400.0 + np.arange(40, dtype="float64") * 0.5, start="2026-04-01")
    rsp = _ohlc(200.0 + np.arange(35, dtype="float64") * 0.7, start="2026-04-01")
    result = compute_rsp_spy(None, _ctx(spy, rsp))
    assert result.data_as_of == rsp.index[-1].date()

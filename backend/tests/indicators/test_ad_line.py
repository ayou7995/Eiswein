"""Watchlist AD Line breadth + SPX divergence (v2 Phase 4)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.ad_line import compute_ad_line


def _spx(close_pattern: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(close_pattern), freq="B")
    return pd.DataFrame({"close": close_pattern}, index=idx, dtype="float64")


def _breadth(net_pattern: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(net_pattern), freq="B")
    # Reconstruct advances / declines from net; magnitudes don't matter
    # for the slope-based classifier, just sign.
    advances = np.where(net_pattern >= 0, np.abs(net_pattern), 0).astype(int)
    declines = np.where(net_pattern < 0, np.abs(net_pattern), 0).astype(int)
    ad_line = np.cumsum(net_pattern)
    return pd.DataFrame(
        {
            "advances": advances,
            "declines": declines,
            "net": net_pattern.astype(int),
            "ad_line": ad_line.astype("float64"),
        },
        index=idx,
    )


def _ctx(spx: pd.DataFrame | None, breadth: pd.DataFrame | None) -> IndicatorContext:
    return IndicatorContext(
        today=date(2026, 6, 5),
        spx_frame=spx,
        watchlist_breadth=breadth,
    )


def test_ad_line_insufficient_when_inputs_missing() -> None:
    assert compute_ad_line(None, _ctx(None, None)).data_sufficient is False
    spx_only = _ctx(_spx(np.arange(30, dtype=float)), None)
    assert compute_ad_line(None, spx_only).data_sufficient is False


def test_ad_line_both_rising_is_green() -> None:
    """SPX rising + AD Line rising = healthy broad rally → GREEN."""
    spx_close = 400.0 + np.arange(30, dtype="float64") * 0.5  # +0.5/day
    breadth_net = np.full(30, 8, dtype=int)  # net advancers each day
    result = compute_ad_line(None, _ctx(_spx(spx_close), _breadth(breadth_net)))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "同步上升" in result.short_label


def test_ad_line_divergence_is_red() -> None:
    """SPX up + AD Line down = narrow rally / negative breadth divergence → RED."""
    spx_close = 400.0 + np.arange(30, dtype="float64") * 0.5
    breadth_net = np.full(30, -8, dtype=int)  # net distribution
    result = compute_ad_line(None, _ctx(_spx(spx_close), _breadth(breadth_net)))
    assert result.signal == SignalTone.RED
    assert "負背離" in result.short_label
    assert result.detail["divergence"] is True


def test_ad_line_both_falling_is_yellow() -> None:
    spx_close = 400.0 - np.arange(30, dtype="float64") * 0.5
    breadth_net = np.full(30, -5, dtype=int)
    result = compute_ad_line(None, _ctx(_spx(spx_close), _breadth(breadth_net)))
    assert result.signal == SignalTone.YELLOW
    assert "同步下" in result.short_label or "盤整" in result.short_label


def test_ad_line_detail_includes_current_day_counts() -> None:
    spx_close = 400.0 + np.arange(30, dtype="float64") * 0.5
    breadth_net = np.full(30, 6, dtype=int)
    result = compute_ad_line(None, _ctx(_spx(spx_close), _breadth(breadth_net)))
    assert {"advances", "declines", "net", "ad_line", "ad_slope_20d", "spx_slope_20d"}.issubset(
        result.detail.keys()
    )
    assert result.detail["advances"] == 6
    assert result.detail["net"] == 6

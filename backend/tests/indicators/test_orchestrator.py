"""Orchestrator: per-indicator failure isolation + expected coverage."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import app.indicators.orchestrator as orch
from app.indicators.base import error_result
from app.indicators.context import IndicatorContext


def test_compute_all_returns_all_expected_names(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(spx_frame=trend_frame)
    results = orch.compute_all("AAPL", trend_frame, ctx)
    expected = {
        "price_vs_ma",
        "rsi",
        "volume_anomaly",
        "relative_strength",
        "macd",
        "bollinger",
        "dxy",
        "fed_rate",
    }
    assert set(results.keys()) == expected


def test_compute_market_regime_returns_four_indicators(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(spx_frame=trend_frame)
    results = orch.compute_market_regime(ctx)
    assert set(results.keys()) == {"spx_ma", "ad_day", "vix", "yield_spread"}


def test_compute_all_isolates_broken_indicator(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Inject a broken compute function into the orchestrator registry.
    def _broken(_frame: pd.DataFrame, _ctx: IndicatorContext) -> object:
        raise ValueError("boom")

    registry = dict(orch._PER_TICKER)
    registry["rsi"] = _broken  # type: ignore[assignment]
    monkeypatch.setattr(orch, "_PER_TICKER", registry)

    ctx = indicator_context_factory(spx_frame=trend_frame)
    results = orch.compute_all("AAPL", trend_frame, ctx)

    # Broken indicator returns error result but does not abort the batch.
    assert results["rsi"].data_sufficient is False
    assert results["rsi"].short_label == "計算錯誤"
    assert "ValueError" in results["rsi"].detail["error"]
    # Every other indicator is present and computed.
    assert len(results) == 8
    # A neighboring indicator (price_vs_ma) still ran fine.
    assert results["price_vs_ma"].data_sufficient is True


def test_error_result_helper_produces_neutral_compute_error() -> None:
    r = error_result("foo", reason="x")
    assert r.signal == "neutral"
    assert r.data_sufficient is False
    assert r.short_label == "計算錯誤"

"""MACD (12,26,9) crossover tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.timing.macd import compute_macd


def _build(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range(
        datetime(2024, 1, 2),
        periods=len(closes),
        freq="B",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def test_insufficient_bars_returns_neutral(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = _build([100.0] * 10)
    ctx = indicator_context_factory()
    result = compute_macd(frame, ctx)
    assert result.data_sufficient is False


def test_macd_computes_full_series(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_macd(trend_frame, ctx)
    assert result.data_sufficient is True
    assert "macd" in result.detail
    assert "signal" in result.detail
    assert "histogram" in result.detail
    assert result.detail["recent_cross"] in {"bullish", "bearish", "none"}


def test_macd_short_label_is_chinese(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_macd(trend_frame, ctx)
    assert any("\u4e00" <= ch <= "\u9fff" for ch in result.short_label)

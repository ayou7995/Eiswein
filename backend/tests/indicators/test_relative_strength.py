"""Relative strength vs SPX tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.direction.relative_strength import compute_relative_strength


def _make_linear(start: float, step: float, days: int = 30) -> pd.DataFrame:
    idx = pd.date_range(
        datetime(2024, 1, 2),
        periods=days,
        freq="B",
        tz="America/New_York",
    )
    closes = [start + i * step for i in range(days)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000] * days,
        },
        index=idx,
    )


def test_ticker_beats_spx_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ticker = _make_linear(100.0, 1.0)  # big gain over 20 days
    spx = _make_linear(100.0, 0.1)
    ctx = indicator_context_factory(spx_frame=spx)
    result = compute_relative_strength(ticker, ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"


def test_ticker_underperforms_spx_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ticker = _make_linear(100.0, -1.0)
    spx = _make_linear(100.0, 0.1)
    ctx = indicator_context_factory(spx_frame=spx)
    result = compute_relative_strength(ticker, ctx)
    assert result.signal == "red"


def test_ticker_matches_spx_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ticker = _make_linear(100.0, 0.1)
    spx = _make_linear(100.0, 0.1)
    ctx = indicator_context_factory(spx_frame=spx)
    result = compute_relative_strength(ticker, ctx)
    assert result.signal == "yellow"


def test_missing_spx_frame_is_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ticker = _make_linear(100.0, 0.5)
    ctx = indicator_context_factory(spx_frame=None)
    result = compute_relative_strength(ticker, ctx)
    assert result.data_sufficient is False

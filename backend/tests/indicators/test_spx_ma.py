"""SPX 50/200 MA indicator tests."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.market_regime.spx_ma import compute_spx_ma


def _chinese(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def test_spx_ma_uptrend_is_green(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_spx_ma(trend_frame, ctx)
    assert result.data_sufficient is True
    # With a mild upward drift the final price should be above both MAs.
    assert result.signal == "green"
    assert _chinese(result.short_label)


def test_spx_ma_flat_frame_is_yellow_or_green(
    flat_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_spx_ma(flat_frame, ctx)
    assert result.data_sufficient is True
    # Flat frame → price == MA50 == MA200; not strictly greater, so YELLOW.
    assert result.signal == "yellow"


def test_spx_ma_short_frame_returns_neutral_insufficient(
    short_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_spx_ma(short_frame, ctx)
    assert result.data_sufficient is False
    assert result.signal == "neutral"
    assert result.short_label == "資料不足"


def test_spx_ma_empty_frame_returns_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_spx_ma(pd.DataFrame(), ctx)
    assert result.data_sufficient is False


def test_spx_ma_detail_contains_mas(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_spx_ma(trend_frame, ctx)
    assert "ma50" in result.detail
    assert "ma200" in result.detail
    assert "price" in result.detail

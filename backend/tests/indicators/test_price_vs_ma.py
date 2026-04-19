"""Per-ticker price vs MA indicator."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.direction.price_vs_ma import compute_price_vs_ma


def test_uptrend_is_green(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_price_vs_ma(trend_frame, ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"


def test_short_frame_is_insufficient(
    short_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_price_vs_ma(short_frame, ctx)
    assert result.data_sufficient is False


def test_handles_nan_in_close(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = trend_frame.copy()
    frame.loc[frame.index[0], "close"] = float("nan")
    ctx = indicator_context_factory()
    result = compute_price_vs_ma(frame, ctx)
    # One NaN in a 260-day frame — should still compute from latest bars.
    assert result.data_sufficient is True


def test_chinese_short_label(
    trend_frame: pd.DataFrame,
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory()
    result = compute_price_vs_ma(trend_frame, ctx)
    assert any("\u4e00" <= ch <= "\u9fff" for ch in result.short_label)

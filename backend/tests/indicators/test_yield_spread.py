"""Yield spread indicator — 10Y-2Y tiers (C8)."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.market_regime.yield_spread import compute_yield_spread
from tests.indicators.conftest import make_macro_frame


def test_healthy_spread_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {
        "DGS10": make_macro_frame([4.5, 4.6, 4.7]),
        "DGS2": make_macro_frame([4.0, 4.1, 4.0]),
    }
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_yield_spread(pd.DataFrame(), ctx)
    assert result.data_sufficient is True
    # Spread 0.7 → GREEN.
    assert result.signal == "green"


def test_flattening_spread_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {
        "DGS10": make_macro_frame([4.05]),
        "DGS2": make_macro_frame([4.00]),
    }
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_yield_spread(pd.DataFrame(), ctx)
    # 0.05 spread — YELLOW tier 0 to 0.2.
    assert result.signal == "yellow"


def test_inverted_spread_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {
        "DGS10": make_macro_frame([3.8]),
        "DGS2": make_macro_frame([4.5]),
    }
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_yield_spread(pd.DataFrame(), ctx)
    assert result.signal == "red"


def test_missing_either_series_returns_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(macro_frames={"DGS10": make_macro_frame([4.0])})
    result = compute_yield_spread(pd.DataFrame(), ctx)
    assert result.data_sufficient is False

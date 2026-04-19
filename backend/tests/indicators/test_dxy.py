"""DXY (DTWEXBGS proxy) indicator tests."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.macro.dxy import compute_dxy
from tests.indicators.conftest import make_macro_frame


def test_rising_streak_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 30 flat bars, then strictly rising 5+ bars → MA20 rises 5 days in a row.
    values = [100.0] * 25 + [100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5]
    macro = {"DTWEXBGS": make_macro_frame(values)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_dxy(pd.DataFrame(), ctx)
    assert result.data_sufficient is True
    assert result.signal == "red"


def test_falling_streak_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    values = [100.0] * 25 + [99.5, 99.0, 98.5, 98.0, 97.5, 97.0, 96.5]
    macro = {"DTWEXBGS": make_macro_frame(values)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_dxy(pd.DataFrame(), ctx)
    assert result.signal == "green"


def test_flat_values_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    values = [100.0] * 35
    macro = {"DTWEXBGS": make_macro_frame(values)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_dxy(pd.DataFrame(), ctx)
    assert result.signal == "yellow"


def test_missing_series_is_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(macro_frames={})
    result = compute_dxy(pd.DataFrame(), ctx)
    assert result.data_sufficient is False

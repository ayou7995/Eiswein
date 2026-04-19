"""Fed Funds Rate indicator tests."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.macro.fed_rate import compute_fed_rate


def _monthly(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"value": values}, index=idx)


def test_cutting_trend_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"FEDFUNDS": _monthly([5.5, 5.25, 5.0, 4.5])}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_fed_rate(pd.DataFrame(), ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"


def test_hiking_trend_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"FEDFUNDS": _monthly([4.0, 4.5, 5.0, 5.5])}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_fed_rate(pd.DataFrame(), ctx)
    assert result.signal == "red"


def test_stable_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"FEDFUNDS": _monthly([5.25, 5.25, 5.25, 5.25])}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_fed_rate(pd.DataFrame(), ctx)
    assert result.signal == "yellow"


def test_missing_series_is_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(macro_frames={})
    result = compute_fed_rate(pd.DataFrame(), ctx)
    assert result.data_sufficient is False


def test_only_one_row_is_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"FEDFUNDS": _monthly([5.25])}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_fed_rate(pd.DataFrame(), ctx)
    # No prior-30d anchor → insufficient.
    assert result.data_sufficient is False

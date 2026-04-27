"""VIX indicator — level + trend."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.market_regime.vix import compute_vix
from tests.indicators.conftest import make_macro_frame


def test_vix_normal_level_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"VIXCLS": make_macro_frame([16.0] * 15 + [17.0] * 5 + [18.0])}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"
    assert result.value == 18.0


def test_vix_panic_level_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # Latest > 30 trips the panic threshold (industry convention).
    macro = {"VIXCLS": make_macro_frame([15.0] * 10 + [20.0, 25.0, 28.0] + [32.0] * 8)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.signal == "red"


def test_vix_complacency_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # Below the 12 threshold = "low" (自滿) zone — yellow.
    macro = {"VIXCLS": make_macro_frame([10.0] * 21)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.signal == "yellow"


def test_vix_includes_percentile_in_detail(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 21 obs of 18 → most-recent 18 ranks at 100% inclusive.
    macro = {"VIXCLS": make_macro_frame([18.0] * 21)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.data_sufficient is True
    assert "percentile_1y" in result.detail
    assert result.detail["percentile_1y"] == 1.0


def test_vix_missing_series_returns_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    ctx = indicator_context_factory(macro_frames={})
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.data_sufficient is False


def test_vix_short_history_returns_insufficient(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    macro = {"VIXCLS": make_macro_frame([18.0] * 3)}
    ctx = indicator_context_factory(macro_frames=macro)
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.data_sufficient is False

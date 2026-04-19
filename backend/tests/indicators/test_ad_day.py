"""A/D Day indicator tests — strict O'Neil."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.market_regime.ad_day import compute_ad_day


def _build_ad_frame(patterns: list[tuple[float, float, int]]) -> pd.DataFrame:
    """patterns: list of (open, close, volume). Frame indexed by business days."""
    idx = pd.date_range(
        datetime(2024, 1, 2),
        periods=len(patterns),
        freq="B",
        tz="America/New_York",
    )
    opens = [p[0] for p in patterns]
    closes = [p[1] for p in patterns]
    vols = [p[2] for p in patterns]
    highs = [max(o, c) + 0.5 for o, c in zip(opens, closes, strict=False)]
    lows = [min(o, c) - 0.5 for o, c in zip(opens, closes, strict=False)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def test_ad_day_strong_accumulation_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 26 bars: first bar + 25 up days with expanding volume → 25 accumulation.
    patterns = [(100.0, 99.5, 1_000_000)]
    base_vol = 1_500_000
    for i in range(25):
        patterns.append((100.0 + i, 101.0 + i, base_vol + i * 50_000))
    frame = _build_ad_frame(patterns)
    ctx = indicator_context_factory()
    result = compute_ad_day(frame, ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"
    assert result.detail["accum_count"] == 25
    assert result.detail["distrib_count"] == 0


def test_ad_day_strong_distribution_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    patterns = [(100.0, 100.5, 1_000_000)]
    base_vol = 1_500_000
    for i in range(25):
        patterns.append((101.0 - i, 100.0 - i, base_vol + i * 50_000))
    frame = _build_ad_frame(patterns)
    ctx = indicator_context_factory()
    result = compute_ad_day(frame, ctx)
    assert result.signal == "red"
    assert result.detail["accum_count"] == 0
    assert result.detail["distrib_count"] == 25


def test_ad_day_flat_volume_is_not_counted(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # 26 bars with declining volume → none counted as accum/distrib.
    patterns = [(100.0, 99.5, 3_000_000)]
    for i in range(25):
        patterns.append((100.0 + i, 101.0 + i, 2_000_000 - i * 10_000))
    frame = _build_ad_frame(patterns)
    ctx = indicator_context_factory()
    result = compute_ad_day(frame, ctx)
    # All up days but volume is DECREASING → no accumulation counted.
    assert result.detail["accum_count"] == 0
    assert result.detail["distrib_count"] == 0


def test_ad_day_insufficient_data_returns_neutral(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = _build_ad_frame([(100.0, 101.0, 1_000_000)] * 5)
    ctx = indicator_context_factory()
    result = compute_ad_day(frame, ctx)
    assert result.data_sufficient is False


def test_ad_day_missing_columns_returns_neutral(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # Frame without "open" column.
    frame = pd.DataFrame(
        {
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
    )
    ctx = indicator_context_factory()
    result = compute_ad_day(frame, ctx)
    assert result.data_sufficient is False

"""Volume anomaly indicator tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pandas as pd

from app.indicators.context import IndicatorContext
from app.indicators.direction.volume_anomaly import compute_volume_anomaly


def _build_frame(closes: list[float], volumes: list[int]) -> pd.DataFrame:
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
            "volume": volumes,
        },
        index=idx,
    )


def test_volume_spike_up_is_green(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    # Last day closes higher with 3x normal volume.
    closes = [100.0] * 21 + [105.0]
    volumes = [1_000_000] * 21 + [3_500_000]
    frame = _build_frame(closes, volumes)
    ctx = indicator_context_factory()
    result = compute_volume_anomaly(frame, ctx)
    assert result.data_sufficient is True
    assert result.signal == "green"
    assert result.detail["spike"] is True


def test_volume_spike_down_is_red(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    closes = [100.0] * 21 + [95.0]
    volumes = [1_000_000] * 21 + [3_500_000]
    frame = _build_frame(closes, volumes)
    ctx = indicator_context_factory()
    result = compute_volume_anomaly(frame, ctx)
    assert result.signal == "red"


def test_normal_volume_is_yellow(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    closes = [100.0 + i * 0.1 for i in range(22)]
    volumes = [1_000_000] * 22
    frame = _build_frame(closes, volumes)
    ctx = indicator_context_factory()
    result = compute_volume_anomaly(frame, ctx)
    assert result.signal == "yellow"
    assert result.detail["spike"] is False


def test_insufficient_bars(
    indicator_context_factory: Callable[..., IndicatorContext],
) -> None:
    frame = _build_frame([100.0] * 5, [1_000_000] * 5)
    ctx = indicator_context_factory()
    result = compute_volume_anomaly(frame, ctx)
    assert result.data_sufficient is False

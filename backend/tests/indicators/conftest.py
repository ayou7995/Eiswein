"""Shared fixtures for indicator tests.

Uses deterministic synthetic frames (NOT live network fetches — rule
2: tests must be hermetic). ``scripts/generate_indicator_fixtures.py``
can regenerate real-market parquet files offline; those files live in
``tests/fixtures/`` and are loaded via :func:`load_fixture` when
present. Tests that assert on specific numeric ranges use the
synthetic fixtures so they are reproducible without network access.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.indicators.context import IndicatorContext

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _make_trend_frame(
    *,
    days: int = 260,
    start_price: float = 100.0,
    drift: float = 0.05,
    noise: float = 0.6,
    seed: int = 7,
) -> pd.DataFrame:
    """Mild uptrend OHLCV — gives deterministic indicator outputs."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(
        "2023-01-02",
        periods=days,
        freq="B",
        tz="America/New_York",
    )
    # Random walk with upward drift.
    returns = rng.normal(drift / 100.0, noise / 100.0, size=days)
    close = start_price * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.002, size=days))
    high = np.maximum(close, open_) * (1.0 + np.abs(rng.normal(0.0, 0.003, size=days)))
    low = np.minimum(close, open_) * (1.0 - np.abs(rng.normal(0.0, 0.003, size=days)))
    volume = rng.integers(500_000, 5_000_000, size=days).astype(np.int64)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _make_flat_frame(days: int = 260, price: float = 100.0) -> pd.DataFrame:
    """Completely flat OHLCV — RSI ≈ 50, MACD ≈ 0."""
    idx = pd.date_range(
        "2023-01-02",
        periods=days,
        freq="B",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": [price] * days,
            "high": [price] * days,
            "low": [price] * days,
            "close": [price] * days,
            "volume": [1_000_000] * days,
        },
        index=idx,
    )


@pytest.fixture
def trend_frame() -> pd.DataFrame:
    return _make_trend_frame()


@pytest.fixture
def flat_frame() -> pd.DataFrame:
    return _make_flat_frame()


@pytest.fixture
def short_frame() -> pd.DataFrame:
    """5-bar frame — insufficient for any indicator requiring history."""
    return _make_trend_frame(days=5)


@pytest.fixture
def indicator_context_factory() -> Callable[..., IndicatorContext]:
    def _factory(
        *,
        today: date | None = None,
        spx_frame: pd.DataFrame | None = None,
        macro_frames: dict[str, pd.DataFrame] | None = None,
    ) -> IndicatorContext:
        return IndicatorContext(
            today=today or date(2024, 12, 31),
            spx_frame=spx_frame,
            macro_frames=macro_frames or {},
        )

    return _factory


def make_macro_frame(values: list[float], start: str = "2023-01-01") -> pd.DataFrame:
    """Date-indexed single-value DataFrame matching FRED's shape."""
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"value": values}, index=idx)


__all__ = ["FIXTURES_DIR", "make_macro_frame"]

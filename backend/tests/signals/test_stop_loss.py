"""Stop-loss calculator tests."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.signals.stop_loss import compute_stop_loss
from app.signals.types import ActionCategory


def _flat_frame(days: int, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2023-01-02", periods=days, freq="B", tz="America/New_York")
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


@pytest.mark.parametrize(
    "action",
    [ActionCategory.STRONG_BUY, ActionCategory.BUY, ActionCategory.HOLD],
)
def test_stop_loss_healthy_branch_uses_200ma(action: ActionCategory) -> None:
    """Healthy trend → 200MA × 0.97. Flat series means MA = 100."""
    frame = _flat_frame(260, price=100.0)
    stop = compute_stop_loss(frame, direction_action=action)
    assert stop == Decimal("97.0000")


def test_stop_loss_healthy_insufficient_history_returns_none() -> None:
    """<200 days → no 200MA → None."""
    frame = _flat_frame(50, price=100.0)
    stop = compute_stop_loss(frame, direction_action=ActionCategory.BUY)
    assert stop is None


@pytest.mark.parametrize(
    "action",
    [ActionCategory.WATCH, ActionCategory.REDUCE, ActionCategory.EXIT],
)
def test_stop_loss_weakening_branch_uses_bb_lower(action: ActionCategory) -> None:
    """Weakening trend with ≥20 bars → BB lower × 0.97."""
    # Descending close so BB lower sits well below the final price.
    days = 60
    idx = pd.date_range("2023-01-02", periods=days, freq="B", tz="America/New_York")
    close = np.linspace(120.0, 100.0, days)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": [1_000_000] * days,
        },
        index=idx,
    )
    stop = compute_stop_loss(frame, direction_action=action)
    assert stop is not None
    # Stop must be strictly below the final close for a meaningful stop.
    assert float(stop) < float(close[-1])


def test_stop_loss_weakening_short_history_uses_5d_low() -> None:
    """<20 bars (no BB) → 5-day low × 0.97."""
    days = 10
    idx = pd.date_range("2023-01-02", periods=days, freq="B", tz="America/New_York")
    close = np.linspace(120.0, 100.0, days)
    low = close - 1.0  # explicit low column
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": low,
            "close": close,
            "volume": [1_000_000] * days,
        },
        index=idx,
    )
    stop = compute_stop_loss(frame, direction_action=ActionCategory.EXIT)
    assert stop is not None
    # Minimum of last 5 lows × 0.97.
    expected = float(pd.Series(low).tail(5).min()) * 0.97
    assert float(stop) == pytest.approx(expected, rel=1e-4)


def test_stop_loss_empty_frame_returns_none() -> None:
    assert compute_stop_loss(pd.DataFrame(), direction_action=ActionCategory.BUY) is None


def test_stop_loss_no_close_column_returns_none() -> None:
    frame = pd.DataFrame({"foo": [1, 2, 3]})
    assert compute_stop_loss(frame, direction_action=ActionCategory.BUY) is None

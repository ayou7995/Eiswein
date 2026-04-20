"""Entry-tier calculator tests."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.signals.entry_price import compute_entry_tiers
from app.signals.types import TimingModifier


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


def test_entry_tiers_flat_series_all_equal_price() -> None:
    """All MAs == price for a flat series → all three tiers same value."""
    frame = _flat_frame(260, price=100.0)
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.MIXED)
    assert tiers.aggressive == Decimal("100.0000")
    assert tiers.ideal == Decimal("100.0000")
    assert tiers.conservative == Decimal("100.0000")


def test_entry_tiers_insufficient_history_returns_none_for_200ma() -> None:
    """Ticker with <200 days but ≥50 → aggressive + ideal set, conservative=None."""
    frame = _flat_frame(60, price=100.0)
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.MIXED)
    assert tiers.aggressive == Decimal("100.0000")
    assert tiers.ideal == Decimal("100.0000")
    assert tiers.conservative is None


def test_entry_tiers_very_short_history_returns_all_none() -> None:
    """<20 days → all three tiers None."""
    frame = _flat_frame(10, price=100.0)
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.MIXED)
    assert tiers.aggressive is None
    assert tiers.ideal is None
    assert tiers.conservative is None


def test_entry_tiers_empty_frame_returns_all_none() -> None:
    tiers = compute_entry_tiers(pd.DataFrame(), timing_modifier=TimingModifier.MIXED)
    assert tiers.aggressive is None
    assert tiers.ideal is None
    assert tiers.conservative is None


def test_entry_tiers_descending_series_uses_bb_lower_when_below_ma200() -> None:
    """Strongly descending series: price < 200MA → conservative uses BB lower."""
    # Build a descending series so the final close is clearly below 200MA.
    days = 260
    idx = pd.date_range("2023-01-02", periods=days, freq="B", tz="America/New_York")
    close = np.linspace(200.0, 100.0, days)  # $200 → $100 linear descent
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
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.UNFAVORABLE)
    assert tiers.conservative is not None
    # BB lower < 200MA here, so conservative is BB-lower, not 200MA.
    ma200 = float(pd.Series(close).rolling(200).mean().iloc[-1])
    assert float(tiers.conservative) < ma200


def test_entry_tiers_split_suggestion_default() -> None:
    frame = _flat_frame(260)
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.MIXED)
    assert tiers.split_suggestion == (30, 40, 30)


def test_entry_tiers_returns_frozen_model() -> None:
    from pydantic import ValidationError

    frame = _flat_frame(260)
    tiers = compute_entry_tiers(frame, timing_modifier=TimingModifier.MIXED)
    with pytest.raises(ValidationError):
        tiers.aggressive = Decimal("200")  # type: ignore[misc]

"""D1b timing classifier — 3-state transitions."""

from __future__ import annotations

from app.indicators.base import SignalTone
from app.signals.timing import classify_timing
from app.signals.types import TimingModifier
from tests.signals.conftest import build_timing_results


def test_timing_both_green_is_favorable() -> None:
    results = build_timing_results(
        macd_signal=SignalTone.GREEN, bollinger_signal=SignalTone.GREEN
    )
    assert classify_timing(results) == TimingModifier.FAVORABLE


def test_timing_both_red_is_unfavorable() -> None:
    results = build_timing_results(
        macd_signal=SignalTone.RED, bollinger_signal=SignalTone.RED
    )
    assert classify_timing(results) == TimingModifier.UNFAVORABLE


def test_timing_mixed_is_mixed() -> None:
    results = build_timing_results(
        macd_signal=SignalTone.GREEN, bollinger_signal=SignalTone.RED
    )
    assert classify_timing(results) == TimingModifier.MIXED


def test_timing_one_yellow_is_mixed() -> None:
    results = build_timing_results(
        macd_signal=SignalTone.GREEN, bollinger_signal=SignalTone.YELLOW
    )
    assert classify_timing(results) == TimingModifier.MIXED


def test_timing_insufficient_data_is_mixed() -> None:
    """A single insufficient-data indicator → MIXED (no vote formed)."""
    results = build_timing_results(
        macd_signal=SignalTone.GREEN,
        bollinger_signal=SignalTone.GREEN,
        macd_sufficient=False,
    )
    assert classify_timing(results) == TimingModifier.MIXED


def test_timing_empty_results_is_mixed() -> None:
    assert classify_timing({}) == TimingModifier.MIXED

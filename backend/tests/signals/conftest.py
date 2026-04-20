"""Shared fixtures for Phase 3 signal tests.

Helper factory to craft ``IndicatorResult`` dicts quickly for
direction / timing / regime classifier tests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from app.indicators.base import IndicatorResult, SignalTone, SignalToneLiteral


def _make_result(
    name: str,
    signal: SignalToneLiteral = SignalTone.NEUTRAL,
    *,
    data_sufficient: bool = True,
    value: float | None = 1.0,
    short_label: str | None = None,
    detail: dict[str, Any] | None = None,
) -> IndicatorResult:
    return IndicatorResult(
        name=name,
        value=value,
        signal=signal,
        data_sufficient=data_sufficient,
        short_label=short_label or f"{name} 測試",
        detail=detail or {},
        computed_at=datetime.now(UTC),
    )


@pytest.fixture
def make_result() -> Callable[..., IndicatorResult]:
    return _make_result


def build_direction_results(greens: int, reds: int, yellows: int = 0) -> dict[str, IndicatorResult]:
    """Construct a 4-indicator direction dict with the specified vote counts.

    Any remaining slots (to reach 4) are filled with YELLOW (neutral
    vote). Intended for the decision-table parametrized tests —
    ``classify_direction`` only cares about GREEN/RED counts.
    """
    names = ["price_vs_ma", "rsi", "volume_anomaly", "relative_strength"]
    if greens + reds + yellows > 4:
        msg = "green + red + yellow votes exceed 4"
        raise ValueError(msg)

    results: dict[str, IndicatorResult] = {}
    signals: list[str] = (
        [SignalTone.GREEN] * greens + [SignalTone.RED] * reds + [SignalTone.YELLOW] * yellows
    )
    while len(signals) < 4:
        signals.append(SignalTone.YELLOW)
    for name, sig in zip(names, signals, strict=True):
        results[name] = _make_result(name, sig)  # type: ignore[arg-type]
    return results


def build_timing_results(
    *,
    macd_signal: SignalToneLiteral = SignalTone.YELLOW,
    bollinger_signal: SignalToneLiteral = SignalTone.YELLOW,
    macd_sufficient: bool = True,
    bollinger_sufficient: bool = True,
) -> dict[str, IndicatorResult]:
    return {
        "macd": _make_result("macd", macd_signal, data_sufficient=macd_sufficient),
        "bollinger": _make_result(
            "bollinger", bollinger_signal, data_sufficient=bollinger_sufficient
        ),
    }


def build_regime_results(greens: int, reds: int, yellows: int = 0) -> dict[str, IndicatorResult]:
    names = ["spx_ma", "ad_day", "vix", "yield_spread"]
    signals: list[str] = (
        [SignalTone.GREEN] * greens + [SignalTone.RED] * reds + [SignalTone.YELLOW] * yellows
    )
    while len(signals) < 4:
        signals.append(SignalTone.YELLOW)
    return {
        name: _make_result(name, sig)  # type: ignore[arg-type]
        for name, sig in zip(names, signals, strict=True)
    }

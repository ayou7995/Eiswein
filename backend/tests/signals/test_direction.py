"""D1a direction classifier — decision table coverage."""

from __future__ import annotations

import pytest

from app.signals.direction import classify_direction
from app.signals.types import ActionCategory
from tests.signals.conftest import _make_result, build_direction_results


@pytest.mark.parametrize(
    ("greens", "reds", "expected_action"),
    [
        # Row 1: 5 green → STRONG_BUY
        (5, 0, ActionCategory.STRONG_BUY),
        # Row 2: 4 green, 0-1 red → BUY
        (4, 0, ActionCategory.BUY),
        (4, 1, ActionCategory.BUY),
        # Row 3: 3 green, 0-1 red → HOLD
        (3, 0, ActionCategory.HOLD),
        (3, 1, ActionCategory.HOLD),
        # Row 4: mixed 1-3 green + 1-2 red → WATCH
        (1, 1, ActionCategory.WATCH),
        (2, 2, ActionCategory.WATCH),
        (3, 2, ActionCategory.WATCH),
        # Row 5: 0-1 green, 3-4 red → REDUCE
        (0, 3, ActionCategory.REDUCE),
        (1, 4, ActionCategory.REDUCE),
        (0, 4, ActionCategory.REDUCE),
        # Row 6: 0 green, 5 red → EXIT
        (0, 5, ActionCategory.EXIT),
    ],
)
def test_direction_classifier_decision_table(
    greens: int, reds: int, expected_action: ActionCategory
) -> None:
    results = build_direction_results(greens, reds)
    action, g, r = classify_direction(results)
    assert action == expected_action
    assert g == greens
    assert r == reds


def test_direction_all_neutral_yellows_is_watch() -> None:
    """5 YELLOW indicators (all data_sufficient) → WATCH via fall-through."""
    results = build_direction_results(0, 0, yellows=5)
    action, g, r = classify_direction(results)
    assert action == ActionCategory.WATCH
    assert g == 0
    assert r == 0


def test_direction_insufficient_data_returns_watch() -> None:
    """All 5 direction indicators have data_sufficient=False → WATCH."""
    results = {
        name: _make_result(name, data_sufficient=False)
        for name in ("price_vs_ma", "rsi", "volume_anomaly", "relative_strength", "cho")
    }
    action, g, r = classify_direction(results)
    assert action == ActionCategory.WATCH
    assert g == 0
    assert r == 0


def test_direction_mixes_insufficient_with_votes() -> None:
    """Insufficient rows are excluded; remaining votes still determine action."""
    results = build_direction_results(4, 0)
    # Mark one green as insufficient — drops green count to 3 → HOLD.
    results["volume_anomaly"] = _make_result("volume_anomaly", data_sufficient=False)
    action, g, r = classify_direction(results)
    assert action == ActionCategory.HOLD
    assert g == 3
    assert r == 0


def test_direction_ignores_unknown_indicator_names() -> None:
    """Indicators not in DIRECTION_INDICATOR_NAMES must not vote."""
    from app.indicators.base import SignalTone

    results = build_direction_results(3, 0)
    results["macd"] = _make_result("macd", SignalTone.GREEN)  # timing, not direction
    action, g, r = classify_direction(results)
    assert action == ActionCategory.HOLD
    assert g == 3

"""earnings_proximity — classifier rule table.

Pure-function indicator: maps days-until-earnings to a tone + label
+ optional force-override badge. Thresholds:

* None / negative → NEUTRAL (no chip)
* < 7              → RED + "⏳ 等財報 Xd"
* 7-30             → YELLOW (no badge)
* > 30             → GREEN (no badge)
"""

from __future__ import annotations

import pytest

from app.indicators.earnings_proximity import (
    ProximityTone,
    classify_earnings_proximity,
)


def test_no_data_returns_neutral() -> None:
    out = classify_earnings_proximity(None)
    assert out.tone is ProximityTone.NEUTRAL
    assert out.force_override_badge is None
    assert out.days_until is None


def test_negative_days_returns_neutral() -> None:
    """A past earnings date is a caller bug — the function must not
    crash and must return NEUTRAL so the UI hides the chip."""
    out = classify_earnings_proximity(-1)
    assert out.tone is ProximityTone.NEUTRAL
    assert out.force_override_badge is None


@pytest.mark.parametrize("days", [0, 1, 3, 6])
def test_lt7_days_triggers_force_override(days: int) -> None:
    out = classify_earnings_proximity(days)
    assert out.tone is ProximityTone.RED
    assert out.force_override_badge == f"⏳ 等財報 {days}d"
    assert out.days_until == days


def test_exactly_7_days_is_yellow_not_red() -> None:
    """The boundary is strict (< 7). Day 7 falls into the YELLOW band."""
    out = classify_earnings_proximity(7)
    assert out.tone is ProximityTone.YELLOW
    assert out.force_override_badge is None


@pytest.mark.parametrize("days", [7, 14, 20, 30])
def test_7_to_30_days_yellow_no_badge(days: int) -> None:
    out = classify_earnings_proximity(days)
    assert out.tone is ProximityTone.YELLOW
    assert out.force_override_badge is None


def test_gt30_days_green() -> None:
    out = classify_earnings_proximity(31)
    assert out.tone is ProximityTone.GREEN
    assert out.force_override_badge is None
    assert out.short_label == "距下次財報 31 天"

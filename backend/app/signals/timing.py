"""D1b — Timing classifier.

Two indicators vote (MACD + Bollinger). Both-green → FAVORABLE, both-red
→ UNFAVORABLE, any other combination (including insufficient data) →
MIXED. No decision table here: the possibility space is small enough
(3³ = 27 before exclusion) that explicit branches are clearer than a
table — but each branch is mechanical with NO precedence judgement, so
this stays within the "decision table, not if/elif" spirit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import TimingModifier

TIMING_INDICATOR_NAMES: Final[frozenset[str]] = frozenset({"macd", "bollinger"})


def classify_timing(results: Mapping[str, IndicatorResult]) -> TimingModifier:
    """Return the timing modifier for the 2 timing indicators.

    If either indicator has ``data_sufficient=False`` the result is
    MIXED — no badge rendered.
    """
    votes = [
        r for name, r in results.items() if name in TIMING_INDICATOR_NAMES and r.data_sufficient
    ]
    if len(votes) < 2:
        return TimingModifier.MIXED

    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)

    if greens == 2:
        return TimingModifier.FAVORABLE
    if reds == 2:
        return TimingModifier.UNFAVORABLE
    return TimingModifier.MIXED

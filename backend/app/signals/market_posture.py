"""Layer 1 — Market posture classifier.

4 market-regime indicators (SPX MA, A/D Day, VIX, 10Y-2Y yield spread)
vote → MarketPosture. Rules:

* 3+ GREEN                            → 進攻 (OFFENSIVE)
* 2+ RED                              → 防守 (DEFENSIVE)
* otherwise                           → 正常 (NORMAL)

Indicators with ``data_sufficient=False`` are excluded from the vote
(C10). When ALL 4 are insufficient, posture defaults to NORMAL rather
than flipping between OFFENSIVE / DEFENSIVE based on zero data (safer
conservative fallback for a market-wide context badge).

Per D2: market posture never silently downgrades per-ticker actions —
it's surfaced as a context badge in the UI only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import MarketPosture

REGIME_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    {"spx_ma", "ad_day", "vix", "yield_spread"}
)


def classify_market_posture(regime_results: Mapping[str, IndicatorResult]) -> MarketPosture:
    """Classify market posture from the 4 regime indicators."""
    votes = [
        r for name, r in regime_results.items() if name in REGIME_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return MarketPosture.NORMAL

    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)

    if greens >= 3:
        return MarketPosture.OFFENSIVE
    if reds >= 2:
        return MarketPosture.DEFENSIVE
    return MarketPosture.NORMAL


def count_regime_tones(
    regime_results: Mapping[str, IndicatorResult],
) -> tuple[int, int, int]:
    """Return ``(green_count, red_count, yellow_count)`` for persistence.

    ``data_sufficient=False`` rows are NEUTRAL and not counted toward any
    of the three — the caller can derive ``neutral = 4 - sum`` if needed.
    """
    votes = [
        r for name, r in regime_results.items() if name in REGIME_INDICATOR_NAMES and r.data_sufficient
    ]
    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)
    yellows = sum(1 for r in votes if r.signal == SignalTone.YELLOW)
    return greens, reds, yellows

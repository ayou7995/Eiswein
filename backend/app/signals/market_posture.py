"""Layer 1 — Market posture classifier (mid-term, 5-vote).

5 market-regime indicators (SPX MA, A/D Day, VIX, 10Y-2Y yield spread,
HYG/IEF credit spread) vote → MarketPosture. Rules:

* 4+ GREEN                            → 進攻 (OFFENSIVE)
* 3+ RED                              → 防守 (DEFENSIVE)
* otherwise                           → 正常 (NORMAL)

The OFFENSIVE bar was lifted from 3/4 to 4/5 because adding a 5th
indicator dilutes per-indicator weight; without lifting the threshold,
"3 green" would trigger OFFENSIVE more often. DEFENSIVE stayed at the
"majority red" level (3/5) — false NORMAL is cheaper than false
DEFENSIVE when posture's job is to flag risk.

Indicators with ``data_sufficient=False`` are excluded from the vote
(C10). When ALL 5 are insufficient, posture defaults to NORMAL rather
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

# v2 (2026-06): hyg_ief joined the vote — credit spread is a genuinely
# orthogonal leading indicator vs equity. spx_adx / rsp_spy / vix_term
# are display-only.
REGIME_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    {"spx_ma", "ad_day", "vix", "yield_spread", "hyg_ief"}
)


def classify_market_posture(regime_results: Mapping[str, IndicatorResult]) -> MarketPosture:
    """Classify market posture from the 5 mid-term regime indicators."""
    votes = [
        r
        for name, r in regime_results.items()
        if name in REGIME_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return MarketPosture.NORMAL

    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)

    if greens >= 4:
        return MarketPosture.OFFENSIVE
    if reds >= 3:
        return MarketPosture.DEFENSIVE
    return MarketPosture.NORMAL


def count_regime_tones(
    regime_results: Mapping[str, IndicatorResult],
) -> tuple[int, int, int]:
    """Return ``(green_count, red_count, yellow_count)`` for persistence.

    ``data_sufficient=False`` rows are NEUTRAL and not counted toward any
    of the three — the caller can derive ``neutral = 5 - sum`` if needed.
    """
    votes = [
        r
        for name, r in regime_results.items()
        if name in REGIME_INDICATOR_NAMES and r.data_sufficient
    ]
    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)
    yellows = sum(1 for r in votes if r.signal == SignalTone.YELLOW)
    return greens, reds, yellows

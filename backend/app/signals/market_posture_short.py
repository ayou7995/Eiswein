"""Layer 1-short — Short-term market posture classifier (days horizon).

Companion to :mod:`app.signals.market_posture` (mid-term, weeks horizon).
The two posture votes run in parallel and produce two ``MarketPosture``
values; the MarketOverview UI shows them side-by-side so the operator
can tell ``中期: 正常 · 短期: 防守`` apart on days like 2026-06-05 when
the market dropped suddenly but the structural picture hasn't broken.

Why two postures
----------------
The mid-term vote uses 4 regime indicators including ``yield_spread``
(recession lead, 12-18 month horizon) and ``spx_ma`` (mid-term trend).
These barely move day-to-day, which is correct for a mid-term gauge but
useless for "is today panic or just noise?".

The short vote uses only the two fastest regime indicators:

* ``vix``     — implied volatility regime, reacts in hours
* ``ad_day``  — last 25 trading days breadth (accumulation/distribution)

A third member (``vix_term`` — VIX/VIX3M ratio) joins in Phase 4.
For Phase 1 we run with the two above.

Decision rule
-------------
With only 2 vote members the symmetric thresholds (3 GREEN → OFFENSIVE,
2 RED → DEFENSIVE) don't translate. Instead:

* 2 GREEN  → OFFENSIVE (low VIX + accumulation = clean buy backdrop)
* 1+ RED   → DEFENSIVE (any signal of panic or distribution is enough)
* else     → NORMAL    (1 GREEN + 1 YELLOW, both YELLOW, etc.)

Asymmetry is deliberate: short-term posture should be quick to flag
risk, slow to declare safety. False NORMAL is cheaper than false
OFFENSIVE on a tactical horizon.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import MarketPosture

REGIME_SHORT_INDICATOR_NAMES: Final[frozenset[str]] = frozenset({"vix", "ad_day"})


def classify_market_posture_short(
    regime_results: Mapping[str, IndicatorResult],
) -> MarketPosture:
    """Classify short-term market posture from the 2 fastest regime indicators.

    All-NEUTRAL fallback returns NORMAL — same conservative default as
    the mid-term classifier, for the same reason (a context badge that
    flips on zero data is misleading)."""
    votes = [
        r
        for name, r in regime_results.items()
        if name in REGIME_SHORT_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return MarketPosture.NORMAL

    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)

    if reds >= 1:
        return MarketPosture.DEFENSIVE
    if greens >= 2:
        return MarketPosture.OFFENSIVE
    return MarketPosture.NORMAL


def count_regime_short_tones(
    regime_results: Mapping[str, IndicatorResult],
) -> tuple[int, int, int]:
    """Return ``(green, red, yellow)`` for persistence."""
    votes = [
        r
        for name, r in regime_results.items()
        if name in REGIME_SHORT_INDICATOR_NAMES and r.data_sufficient
    ]
    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)
    yellows = sum(1 for r in votes if r.signal == SignalTone.YELLOW)
    return greens, reds, yellows

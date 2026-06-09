"""Layer 1-short — Short-term market posture classifier (days horizon).

Companion to :mod:`app.signals.market_posture` (mid-term, weeks horizon).
The two posture votes run in parallel and produce two ``MarketPosture``
values; the MarketOverview UI shows them side-by-side so the operator
can tell ``中期: 正常 · 短期: 防守`` apart on days like 2026-06-05 when
the market dropped suddenly but the structural picture hasn't broken.

Why two postures
----------------
The mid-term vote uses 6 regime indicators including ``yield_spread``
(recession lead, 12-18 month horizon) and ``spx_ma`` (mid-term trend).
These barely move day-to-day, which is correct for a mid-term gauge but
useless for "is today panic or just noise?".

The short vote uses four fast regime indicators (Phase 5 added SKEW):

* ``vix``      — implied volatility level, reacts in hours
* ``ad_day``   — last 25 trading days breadth (accumulation/distribution)
* ``vix_term`` — VIX/VIX3M ratio (curve inversion = immediate stress)
* ``skew``     — CBOE Skew Index (institutional OTM put bid; the
                 quiet-VIX/rising-SKEW divergence is exactly the kind of
                 build-up the other three indicators miss)

Decision rule
-------------
With 4 vote members the rule is:

* 4 GREEN  → OFFENSIVE (all calm + accumulating + low tail-risk pricing
  = clean buy backdrop; deliberately strict so partial signals don't
  trip the offensive flag)
* 2+ RED   → DEFENSIVE (multiple panic signals)
* else     → NORMAL

Asymmetry is deliberate: short-term posture should be quick to flag
risk, slow to declare safety. False NORMAL is cheaper than false
OFFENSIVE on a tactical horizon. The earlier 3-vote rule "1+ RED →
DEFENSIVE" relaxed to "2+ RED" because a 4-vote table makes 1/4 = 25 %
RED too noisy — a single VIX spike could flip the badge without any
corroboration from breadth, curve, or skew.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import MarketPosture

REGIME_SHORT_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    {"vix", "ad_day", "vix_term", "skew"}
)


def classify_market_posture_short(
    regime_results: Mapping[str, IndicatorResult],
) -> MarketPosture:
    """Classify short-term market posture from the 4 fastest regime indicators.

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

    if reds >= 2:
        return MarketPosture.DEFENSIVE
    if greens >= 4:
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

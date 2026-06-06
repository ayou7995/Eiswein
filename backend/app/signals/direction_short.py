"""D1a-short — Short-term direction classifier (3-5 days horizon).

Companion to :mod:`app.signals.direction` (which is the mid-term vote
on the same 6-action ladder, 2-4 weeks horizon). The two votes run in
parallel and produce two ``ActionCategory`` values per ticker; the UI
renders them side-by-side as a dual badge.

Why two votes instead of one
----------------------------
The 4 mid-term indicators (price_vs_ma, rsi, volume_anomaly,
relative_strength) are noisy at the 3-5 day horizon — relative_strength
in particular has a multi-week decay. For tactical short-term decisions
("today the market dropped, can I enter?"), we want a vote that:

* responds within days, not weeks
* doesn't get dragged down by slow indicators
* surfaces oversold-bounce + breakout-from-squeeze setups

Vote members:
* ``rsi``            — fastest oscillator (5-week lookback, day-level swings)
* ``macd``           — momentum crossover (5-day signal smoothing)
* ``bollinger``      — channel position (day-level mean reversion)
* ``volume_anomaly`` — today's flow vs 20-day average (next-day continuation)

TTM Squeeze joins in Phase 3 (5-vote table); for Phase 1 we run with
the 4 above, sharing the same decision table shape as mid-term.

Implementation mirrors :mod:`app.signals.direction` exactly so the two
classifiers stay symmetric and the maintenance burden of "two parallel
6-action ladders" stays low.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import ActionCategory

DIRECTION_SHORT_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    # v2 Phase 3 (2026-06): TTM Squeeze added — the breakout-direction
    # gauge. The table below is a 5-vote scale (was 4-vote in Phase 1).
    {"rsi", "macd", "bollinger", "volume_anomaly", "ttm_squeeze"}
)


# 5-vote decision table (Phase 3). Proportionally widened from the
# 4-vote shape so the rough action ladder is preserved:
#   ≥80% green       → STRONG_BUY
#    60-79% green    → BUY
#    50-59% green    → HOLD
#    mixed / near-tied → WATCH
#    majority red     → REDUCE
#    100% red         → EXIT
# Tuple order: (min_green, max_green, min_red, max_red, action).
_DIRECTION_SHORT_TABLE: Final[tuple[tuple[int, int, int, int, ActionCategory], ...]] = (
    (5, 5, 0, 0, ActionCategory.STRONG_BUY),
    (4, 4, 0, 1, ActionCategory.BUY),
    (3, 3, 0, 1, ActionCategory.HOLD),
    (1, 3, 1, 2, ActionCategory.WATCH),
    (0, 1, 3, 4, ActionCategory.REDUCE),
    (0, 0, 5, 5, ActionCategory.EXIT),
)


def classify_direction_short(
    results: Mapping[str, IndicatorResult],
) -> tuple[ActionCategory, int, int]:
    """Classify short-term direction action + return (green, red) counts.

    All-NEUTRAL fallback (no indicator has ``data_sufficient=True``)
    returns ``(WATCH, 0, 0)`` — same convention as mid-term. The UI
    surfaces this as 「⚪ 資料不足以判斷」 rather than 「觀望」.
    """
    votes = [
        r
        for name, r in results.items()
        if name in DIRECTION_SHORT_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return ActionCategory.WATCH, 0, 0

    green = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    red = sum(1 for r in votes if r.signal == SignalTone.RED)

    for min_g, max_g, min_r, max_r, action in _DIRECTION_SHORT_TABLE:
        if min_g <= green <= max_g and min_r <= red <= max_r:
            return action, green, red

    return ActionCategory.WATCH, green, red

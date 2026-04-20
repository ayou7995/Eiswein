"""D1a — Direction classifier (decision table, NOT if/elif).

Counts GREEN and RED votes across the 4 direction indicators and
returns an :class:`ActionCategory`. Mirror of the table in
``docs/STAFF_REVIEW_DECISIONS.md § D1``:

| Direction 🟢 | Direction 🔴 | Action       |
|-------------|-------------|--------------|
| 4           | 0           | 強力買入 🟢🟢 |
| 3           | 0-1         | 買入 🟢       |
| 2           | 0-1         | 持有 ✓        |
| 1-2         | 1-2         | 觀望 👀       |
| 0-1         | 2-3         | 減倉 ⚠️       |
| 0           | 4           | 出場 🔴🔴     |

Implemented as a tuple of ``(min_green, max_green, min_red, max_red,
action)`` rows scanned top-to-bottom so higher-conviction actions win
ties on boundary cases (e.g. 2🟢/1🔴 → 持有, not 觀望). This is
deliberate: if/elif chains were the original temptation, but the user
mandated decision-table form for auditability.

All-NEUTRAL case (all 4 indicators have ``data_sufficient=False``)
returns WATCH with zero counts — see I19 + D1 "All-NEUTRAL" rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import ActionCategory

# Canonical direction indicator names. Declared here (not imported from
# ``orchestrator``) so this module stays free of indicator-impl imports —
# it's a pure classifier that only reads result dicts by key.
DIRECTION_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    {"price_vs_ma", "rsi", "volume_anomaly", "relative_strength"}
)


# (min_green, max_green, min_red, max_red, action)
# Scanned in order: higher-conviction rows (more GREEN / more RED) come
# first. No row for (2🟢, 2🔴) — that falls through to WATCH below.
_DIRECTION_TABLE: Final[tuple[tuple[int, int, int, int, ActionCategory], ...]] = (
    (4, 4, 0, 0, ActionCategory.STRONG_BUY),
    (3, 3, 0, 1, ActionCategory.BUY),
    (2, 2, 0, 1, ActionCategory.HOLD),
    (1, 2, 1, 2, ActionCategory.WATCH),
    (0, 1, 2, 3, ActionCategory.REDUCE),
    (0, 0, 4, 4, ActionCategory.EXIT),
)


def classify_direction(
    results: Mapping[str, IndicatorResult],
) -> tuple[ActionCategory, int, int]:
    """Classify the direction action + return (green, red) vote counts.

    Indicators with ``data_sufficient=False`` are excluded from the vote
    (per C10). When NONE of the 4 direction indicators have sufficient
    data, returns ``(WATCH, 0, 0)`` so the UI can surface the "資料不足
    以判斷" note without collapsing to a harder action.
    """
    votes = [
        r for name, r in results.items() if name in DIRECTION_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return ActionCategory.WATCH, 0, 0

    green = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    red = sum(1 for r in votes if r.signal == SignalTone.RED)

    for min_g, max_g, min_r, max_r, action in _DIRECTION_TABLE:
        if min_g <= green <= max_g and min_r <= red <= max_r:
            return action, green, red

    # Mixed case (e.g. 2🟢 + 2🔴) — WATCH is the explicit fallback.
    return ActionCategory.WATCH, green, red

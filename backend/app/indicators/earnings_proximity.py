"""Earnings Date Proximity — the deferred indicator from
`docs/indicators-roadmap.md` §4.4.

Sits across layers — it does NOT vote into D1a / D1b / Posture, but
*overrides* the timing badge when an earnings event is < 7 calendar
days away ("⏳ 等財報 Xd"). The composed action stays whatever the
4-vote direction layer produced; the overlaid badge nudges the operator
not to enter a new position right before an earnings reversal.

Pure functions only. The calendar lookup lives in the API route and the
daily_update orchestrator — those modules pass ``days_until_earnings``
into :func:`classify_earnings_proximity` here.

Thresholds (from the roadmap):

* < 7 days → RED, force_override = "⏳ 等財報 Xd"  (避免新建倉)
* 7-30 days → YELLOW (cautious; no badge override)
* > 30 days → GREEN (technical signals reliable; no badge)
* None     → 無資料 (no chip; do not break the UI)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

INDICATOR_NAME = "earnings_proximity"

# Boundary days. The "<7" rule is the explicit override boundary the
# roadmap calls out; everything else is informational.
_FORCE_OVERRIDE_THRESHOLD = 7
_YELLOW_THRESHOLD = 30


class ProximityTone(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class EarningsProximityResult:
    """Decision output of :func:`classify_earnings_proximity`.

    ``days_until`` is preserved so callers can render "4d" without a
    second calculation. ``force_override_badge`` is the literal badge
    text to splice into the wire response when non-None.
    """

    days_until: int | None
    tone: ProximityTone
    short_label: str
    force_override_badge: str | None


def classify_earnings_proximity(days_until: int | None) -> EarningsProximityResult:
    """Map the day-distance to (tone, label, optional override badge).

    Negative ``days_until`` (event already happened) returns NEUTRAL —
    callers feeding past dates likely have a bug, but the function
    must not crash.
    """
    if days_until is None or days_until < 0:
        return EarningsProximityResult(
            days_until=None,
            tone=ProximityTone.NEUTRAL,
            short_label="無下次財報資料",
            force_override_badge=None,
        )
    if days_until < _FORCE_OVERRIDE_THRESHOLD:
        return EarningsProximityResult(
            days_until=days_until,
            tone=ProximityTone.RED,
            short_label=f"距下次財報 {days_until} 天",
            force_override_badge=f"⏳ 等財報 {days_until}d",
        )
    if days_until <= _YELLOW_THRESHOLD:
        return EarningsProximityResult(
            days_until=days_until,
            tone=ProximityTone.YELLOW,
            short_label=f"距下次財報 {days_until} 天",
            force_override_badge=None,
        )
    return EarningsProximityResult(
        days_until=days_until,
        tone=ProximityTone.GREEN,
        short_label=f"距下次財報 {days_until} 天",
        force_override_badge=None,
    )

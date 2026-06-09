"""Layer 1 — Market posture classifier (mid-term, 6-vote).

6 market-regime indicators vote → MarketPosture:

* spx_ma       (mid)   — SPX vs 50/200 MA
* ad_day       (short) — Accumulation/Distribution day count
* vix          (short) — VIX level + 10-day trend
* yield_spread (long)  — 10Y-2Y Treasury curve
* hyg_ief      (mid)   — HY corp bond vs Treasury (credit spread)
* unrate       (long)  — US unemployment + Sahm Rule recession trigger

(SKEW is short-only — it votes in the separate ``market_posture_short``
4-vote table, NOT here.)

Rules:

* ≥5 GREEN                            → 進攻 (OFFENSIVE)
* ≥4 RED                              → 防守 (DEFENSIVE)
* otherwise                           → 正常 (NORMAL)

Threshold rationale: 5/6 ≈ 83 % keeps the "strong majority" bar for
OFFENSIVE close to the previous 4/5 = 80 %; 4/6 ≈ 67 % is slightly
stricter than the prior 3/5 = 60 % DEFENSIVE bar — a deliberate
calibration to avoid more frequent DEFENSIVE flips now that an extra
vote (UNRATE) sits in the table.

Indicators with ``data_sufficient=False`` are excluded from the vote
(C10). When ALL 6 are insufficient, posture defaults to NORMAL.
Display-only regime indicators (spx_adx, rsp_spy, vix_term) appear in
the dashboard cards but never enter the vote.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import MarketPosture

# v3 (2026-06 Phase 5): unrate joined the mid posture (Sahm Rule
# recession trigger). skew lives in market_posture_short.
REGIME_INDICATOR_NAMES: Final[frozenset[str]] = frozenset(
    {"spx_ma", "ad_day", "vix", "yield_spread", "hyg_ief", "unrate"}
)


def classify_market_posture(regime_results: Mapping[str, IndicatorResult]) -> MarketPosture:
    """Classify market posture from the 6 mid-term regime indicators."""
    votes = [
        r
        for name, r in regime_results.items()
        if name in REGIME_INDICATOR_NAMES and r.data_sufficient
    ]
    if not votes:
        return MarketPosture.NORMAL

    greens = sum(1 for r in votes if r.signal == SignalTone.GREEN)
    reds = sum(1 for r in votes if r.signal == SignalTone.RED)

    if greens >= 5:
        return MarketPosture.OFFENSIVE
    if reds >= 4:
        return MarketPosture.DEFENSIVE
    return MarketPosture.NORMAL


def count_regime_tones(
    regime_results: Mapping[str, IndicatorResult],
) -> tuple[int, int, int]:
    """Return ``(green_count, red_count, yellow_count)`` for persistence.

    ``data_sufficient=False`` rows are NEUTRAL and not counted toward any
    of the three — the caller can derive ``neutral = 6 - sum`` if needed.
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

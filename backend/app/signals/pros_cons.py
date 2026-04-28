"""Pros/Cons structured list builder.

The user-facing "plain-language" summary for the dashboard is a
scannable list of 🟢/🔴/⚪ bullets, NOT a prose paragraph. This module
converts a dict of ``IndicatorResult`` into :class:`ProsConsItem`
entries with ONE rule per indicator:

* category mapped by indicator name (direction / timing / macro)
* tone derived from signal (GREEN → pro, RED → con, else neutral)
* ``short_label`` passed through verbatim — we do NOT concatenate,
  format, or otherwise synthesize prose. The label is already a
  structured Chinese summary produced by the indicator module.

UX rule (``CLAUDE.md``): if rich narrative becomes necessary post-v1,
we hand the IndicatorResult dict off to an LLM (Haiku/Flash) with a
strict JSON prompt. Never a hand-coded template.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.indicators.base import IndicatorResult, SignalTone
from app.indicators.timeframes import INDICATOR_TIMEFRAMES
from app.signals.types import (
    ProsConsCategoryLiteral,
    ProsConsItem,
    ProsConsToneLiteral,
)

_DIRECTION_NAMES: Final[frozenset[str]] = frozenset(
    {"price_vs_ma", "rsi", "volume_anomaly", "relative_strength"}
)
_TIMING_NAMES: Final[frozenset[str]] = frozenset({"macd", "bollinger"})
# Per-ticker macro + market-regime indicators both surface under the
# "macro" category at the domain layer — the frontend can split them
# visually (大盤 vs 總經) using the indicator_name.
_MACRO_NAMES: Final[frozenset[str]] = frozenset(
    {"dxy", "fed_rate", "spx_ma", "ad_day", "vix", "yield_spread"}
)


def build_pros_cons_items(
    results: Mapping[str, IndicatorResult],
) -> list[ProsConsItem]:
    """Translate indicator results into an ordered Pros/Cons list.

    Ordering: indicators are emitted in the order they appear in
    ``results``. Callers that care about a stable UI ordering should
    pass a dict keyed in the desired order (Python 3.7+ preserves
    insertion order).
    """
    items: list[ProsConsItem] = []
    for name, result in results.items():
        category = _category_for(name)
        if category is None:
            # Unknown indicator name — skip rather than mis-classify.
            # This keeps the list coherent if a future indicator is
            # added before its category mapping is updated.
            continue
        tone = _tone_for(result)
        # Skip indicators not in the timeframe map for the same reason
        # we skip unknown categories — better to drop than mis-classify.
        if name not in INDICATOR_TIMEFRAMES:
            continue
        items.append(
            ProsConsItem(
                category=category,
                tone=tone,
                short_label=result.short_label,
                detail=dict(result.detail),
                indicator_name=result.name,
                timeframe=INDICATOR_TIMEFRAMES[name],
            )
        )
    return items


def _category_for(name: str) -> ProsConsCategoryLiteral | None:
    if name in _DIRECTION_NAMES:
        return "direction"
    if name in _TIMING_NAMES:
        return "timing"
    if name in _MACRO_NAMES:
        return "macro"
    return None


def _tone_for(result: IndicatorResult) -> ProsConsToneLiteral:
    if not result.data_sufficient:
        return "neutral"
    if result.signal == SignalTone.GREEN:
        return "pro"
    if result.signal == SignalTone.RED:
        return "con"
    return "neutral"

"""Signal composition — glue between D1a / D1b / Layer 1 classifiers.

Given an already-classified ``(action, green, red, timing_mod, posture)``
tuple plus entry/stop-loss outputs, produce the frozen
:class:`ComposedSignal` snapshot that the ingestion layer persists and
the API endpoint serializes.

The ``should_show_timing`` rule enforces D1b: the timing modifier only
surfaces for buy-side actions (強力買入, 買入, 持有). For 觀望/減倉/出場
the timing badge is suppressed because it's not relevant to an
exit-side decision.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from app.indicators.base import INDICATOR_VERSION
from app.signals.types import (
    ActionCategory,
    ComposedSignal,
    EntryTiers,
    MarketPosture,
    TimingModifier,
)

_BUY_SIDE_ACTIONS: Final[frozenset[ActionCategory]] = frozenset(
    {ActionCategory.STRONG_BUY, ActionCategory.BUY, ActionCategory.HOLD}
)


def should_show_timing(action: ActionCategory) -> bool:
    """Return True when the timing modifier badge should be rendered.

    D1b: timing is only meaningful for buy-side actions. For 觀望/減倉/
    出場, the user is not entering — timing is noise.
    """
    return action in _BUY_SIDE_ACTIONS


def compose_signal(
    *,
    symbol: str,
    trade_date: date,
    action: ActionCategory,
    direction_green_count: int,
    direction_red_count: int,
    timing_modifier: TimingModifier,
    market_posture: MarketPosture,
    entry_tiers: EntryTiers,
    stop_loss: Decimal | None,
    indicator_version: str = INDICATOR_VERSION,
    computed_at: datetime | None = None,
) -> ComposedSignal:
    """Assemble the final :class:`ComposedSignal` record.

    Thin adapter — all decision logic is upstream in the classifiers.
    Keeping this as a function (rather than a ``ComposedSignal``
    factory classmethod) avoids coupling the domain type to the
    composition algorithm.
    """
    return ComposedSignal(
        symbol=symbol,
        date=trade_date,
        action=action,
        direction_green_count=direction_green_count,
        direction_red_count=direction_red_count,
        timing_modifier=timing_modifier,
        show_timing_modifier=should_show_timing(action),
        entry_tiers=entry_tiers,
        stop_loss=stop_loss,
        market_posture_at_compute=market_posture,
        indicator_version=indicator_version,
        computed_at=computed_at or datetime.now(UTC),
    )

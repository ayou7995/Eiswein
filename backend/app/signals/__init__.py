"""Phase 3 signal composition layer.

Pure-function decision tables (D1 mandate) that convert indicator
results into ActionCategory + TimingModifier + MarketPosture and
compose the final per-ticker :class:`ComposedSignal`. No network,
no DB imports in this package — see ``app/ingestion/signals.py`` for
the persistence wiring.
"""

from __future__ import annotations

from app.signals.types import (
    ActionCategory,
    ComposedSignal,
    EntryTiers,
    MarketPosture,
    ProsConsItem,
    TimingModifier,
)

__all__ = [
    "ActionCategory",
    "ComposedSignal",
    "EntryTiers",
    "MarketPosture",
    "ProsConsItem",
    "TimingModifier",
]

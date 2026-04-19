"""Pure-function indicator engine (Phase 2).

Indicators consume pre-fetched OHLCV DataFrames + a shared
:class:`IndicatorContext`; they NEVER perform network I/O. The
ingestion layer (``app/ingestion``) is the single source of truth for
pulling raw data — see the ``Indicators are pure functions`` invariant
in ``CLAUDE.md``.

``INDICATOR_VERSION`` is persisted with every computed
:class:`~app.indicators.base.IndicatorResult`; bump this whenever any
formula or threshold changes so historical results can be
distinguished from current ones (A2 in
``docs/STAFF_REVIEW_DECISIONS.md``).
"""

from __future__ import annotations

from app.indicators.base import (
    INDICATOR_VERSION,
    Indicator,
    IndicatorResult,
    SignalTone,
    SignalToneLiteral,
)
from app.indicators.context import IndicatorContext

__all__ = [
    "INDICATOR_VERSION",
    "Indicator",
    "IndicatorContext",
    "IndicatorResult",
    "SignalTone",
    "SignalToneLiteral",
]

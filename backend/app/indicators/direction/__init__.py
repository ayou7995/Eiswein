"""Direction indicators (4): Price vs MA, RSI, volume anomaly, RS vs SPX.

Phase 3 ``signals/compose.py`` votes over these four per-ticker
results to produce the :class:`ActionCategory` (see D1 in
``docs/STAFF_REVIEW_DECISIONS.md``).
"""

from __future__ import annotations

from app.indicators.direction.price_vs_ma import compute_price_vs_ma
from app.indicators.direction.relative_strength import compute_relative_strength
from app.indicators.direction.rsi import compute_rsi
from app.indicators.direction.volume_anomaly import compute_volume_anomaly

__all__ = [
    "compute_price_vs_ma",
    "compute_relative_strength",
    "compute_rsi",
    "compute_volume_anomaly",
]

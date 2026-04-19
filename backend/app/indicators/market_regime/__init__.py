"""Market-regime indicators (4): SPX MA, A/D Day, VIX, yield spread.

Composed by the Phase 3 signal layer into an overall Market Posture
(進攻/正常/防守). Each module here returns a single
:class:`IndicatorResult` — no cross-indicator logic lives here.
"""

from __future__ import annotations

from app.indicators.market_regime.ad_day import compute_ad_day
from app.indicators.market_regime.spx_ma import compute_spx_ma
from app.indicators.market_regime.vix import compute_vix
from app.indicators.market_regime.yield_spread import compute_yield_spread

__all__ = [
    "compute_ad_day",
    "compute_spx_ma",
    "compute_vix",
    "compute_yield_spread",
]

"""Macro indicators (2): DXY direction + Fed Funds Rate.

Both consume FRED series from ``context.macro_frames`` — ``DTWEXBGS``
(DXY proxy, documented in README) and ``FEDFUNDS``.
"""

from __future__ import annotations

from app.indicators.macro.dxy import compute_dxy
from app.indicators.macro.fed_rate import compute_fed_rate

__all__ = ["compute_dxy", "compute_fed_rate"]

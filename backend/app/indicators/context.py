"""Shared cross-indicator input container.

Holds the data that several indicators need in common: the SPX frame
(for market-regime + per-ticker relative strength), the macro series
DataFrames (VIX, yield spread, DXY, Fed Funds), and today's exchange
date. Passed in once from the orchestrator so each indicator stays a
pure DataFrame-in / result-out function.

Instance is immutable (``frozen=True``). Mutating it after
construction is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.indicators.base import INDICATOR_VERSION


@dataclass(frozen=True)
class IndicatorContext:
    """Inputs required by indicators beyond the per-ticker frame."""

    today: date
    indicator_version: str = INDICATOR_VERSION
    spx_frame: pd.DataFrame | None = None
    macro_frames: dict[str, pd.DataFrame] = field(default_factory=dict)

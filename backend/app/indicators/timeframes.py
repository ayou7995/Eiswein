"""Per-indicator timeframe classification.

The 12 indicators span three horizons. Surfacing this as a chip on each
pros/cons row lets the operator answer "which horizon is this signal
talking about?" at a glance without reading the indicator docs.

Single source of truth: backend authoritative, frontend mirrors via the
API response shape.

Mapping rationale (matches CLAUDE.md "Core Indicators (12)"):

* short  — same-day or week-to-week tactical signals: RSI(14),
  Bollinger band reversion, MACD cross, today's volume anomaly,
  today's A/D Day Count, current VIX level.
* mid    — multi-week trend / regime: 50-day MA distance, relative
  strength vs SPX over a few weeks, the 50/200 SMA cross of SPX itself.
* long   — multi-month / multi-quarter macro: 200-day MA dominance,
  10Y-2Y yield spread (recession indicator), DXY (USD strength regime),
  Fed Funds Rate (policy regime).

Each indicator's primary horizon is captured. Indicators that touch
more than one timeframe (e.g. RSI uses both daily and weekly windows)
get the *dominant* horizon — the one that drives the buy/sell call.
"""

from __future__ import annotations

from typing import Final, Literal

Timeframe = Literal["short", "mid", "long"]

INDICATOR_TIMEFRAMES: Final[dict[str, Timeframe]] = {
    # Per-ticker direction (4)
    "price_vs_ma": "mid",
    "rsi": "short",
    "volume_anomaly": "short",
    "relative_strength": "mid",
    # Market regime (4)
    "spx_ma": "mid",
    "ad_day": "short",
    "vix": "short",
    "yield_spread": "long",
    # Timing (2)
    "macd": "short",
    "bollinger": "short",
    # Macro (2)
    "dxy": "long",
    "fed_rate": "long",
}


def timeframe_for(indicator_name: str) -> Timeframe:
    """Look up the timeframe for an indicator NAME.

    Raises ``KeyError`` for unknown names — callers (which hold the
    indicator NAME constants directly) should not be guessing.
    """
    return INDICATOR_TIMEFRAMES[indicator_name]


__all__ = ("INDICATOR_TIMEFRAMES", "Timeframe", "timeframe_for")

"""Indicator compute orchestrator.

Runs every per-ticker indicator in a try/except so a single broken
indicator does not abort the batch (rule 14: graceful degradation) —
instead the failing indicator gets a NEUTRAL result with
``short_label="計算錯誤"``. This mirrors the ingestion-layer policy
where a single failing ticker does not abort the daily update.

This module is the *only* place that knows which indicator modules
exist. Callers should rely on the returned dict's keys rather than
introspecting the indicators package.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pandas as pd
import structlog

from app.indicators.base import IndicatorResult, error_result
from app.indicators.direction.cho import compute_cho
from app.indicators.direction.price_vs_ma import compute_price_vs_ma
from app.indicators.direction.relative_strength import compute_relative_strength
from app.indicators.direction.rsi import compute_rsi
from app.indicators.direction.volume_anomaly import compute_volume_anomaly
from app.indicators.macro.dxy import compute_dxy
from app.indicators.macro.fed_rate import compute_fed_rate
from app.indicators.market_regime.ad_day import compute_ad_day
from app.indicators.market_regime.ad_line import compute_ad_line
from app.indicators.market_regime.spx_adx import compute_spx_adx
from app.indicators.market_regime.spx_ma import compute_spx_ma
from app.indicators.market_regime.vix import compute_vix
from app.indicators.market_regime.vix_term import compute_vix_term
from app.indicators.market_regime.yield_spread import compute_yield_spread
from app.indicators.timing.adx import compute_adx
from app.indicators.timing.atr import compute_atr
from app.indicators.timing.bollinger import compute_bollinger
from app.indicators.timing.macd import compute_macd
from app.indicators.timing.ttm_squeeze import compute_ttm_squeeze

if TYPE_CHECKING:
    from app.indicators.context import IndicatorContext

logger = structlog.get_logger("eiswein.indicators.orchestrator")

IndicatorFunc = Callable[[pd.DataFrame, "IndicatorContext"], IndicatorResult]


# Per-ticker indicators: direction + timing + macro.
# Name → compute function. Macro indicators use the ticker frame as a
# placeholder and read their series from ``context.macro_frames``.
_PER_TICKER: dict[str, IndicatorFunc] = {
    "price_vs_ma": compute_price_vs_ma,
    "rsi": compute_rsi,
    "volume_anomaly": compute_volume_anomaly,
    "relative_strength": compute_relative_strength,
    "macd": compute_macd,
    "bollinger": compute_bollinger,
    # v2 Phase 2 (2026-06): ADX as a mid-term trust modifier on the
    # other direction signals; ATR as the volatility gauge that feeds
    # stop-loss sizing + the "today's move unusual?" headline.
    "adx": compute_adx,
    "atr": compute_atr,
    # v2 Phase 3 (2026-06): TTM Squeeze joins the short-term vote as
    # the breakout-direction gauge; CHO joins the mid-term vote as the
    # accumulation/distribution accelerator (Sherry-style 大戶吃貨 read).
    "ttm_squeeze": compute_ttm_squeeze,
    "cho": compute_cho,
    "dxy": compute_dxy,
    "fed_rate": compute_fed_rate,
}

_MARKET_REGIME: dict[str, IndicatorFunc] = {
    "spx_ma": compute_spx_ma,
    "ad_day": compute_ad_day,
    "vix": compute_vix,
    "yield_spread": compute_yield_spread,
    # v2 Phase 2: market-wide trend strength. Pairs with spx_ma (which
    # gives direction) — when SPX is above 200MA and SPX ADX > 25 the
    # trend is real; SPX above 200MA but ADX < 20 means we're drifting.
    "spx_adx": compute_spx_adx,
    # v2 Phase 4: VIX term structure (spot vs 3M) for short-term stress
    # signal; cumulative watchlist A/D Line for breadth-vs-SPX divergence.
    "vix_term": compute_vix_term,
    "ad_line": compute_ad_line,
}


def compute_all(
    symbol: str,
    price_frame: pd.DataFrame,
    context: IndicatorContext,
) -> dict[str, IndicatorResult]:
    """Compute all 8 per-ticker indicators from a single OHLCV frame.

    Each indicator runs isolated from the others via try/except.
    Returns a dict keyed by indicator name so callers can persist /
    render without knowing the underlying module layout.
    """
    results: dict[str, IndicatorResult] = {}
    for name, fn in _PER_TICKER.items():
        results[name] = _safe_run(name, fn, price_frame, context, symbol=symbol)
    return results


def compute_market_regime(context: IndicatorContext) -> dict[str, IndicatorResult]:
    """Compute the 4 market-regime indicators.

    The SPX frame is passed through as the primary frame for
    ``spx_ma``/``ad_day``; VIX + yield spread read their series from
    ``context.macro_frames``.
    """
    results: dict[str, IndicatorResult] = {}
    spx = context.spx_frame if context.spx_frame is not None else pd.DataFrame()
    for name, fn in _MARKET_REGIME.items():
        results[name] = _safe_run(name, fn, spx, context, symbol="SPX")
    return results


def _safe_run(
    name: str,
    fn: IndicatorFunc,
    frame: pd.DataFrame,
    context: IndicatorContext,
    *,
    symbol: str,
) -> IndicatorResult:
    try:
        return fn(frame, context)
    except (ValueError, TypeError, ArithmeticError, KeyError, IndexError) as exc:
        logger.warning(
            "indicator_compute_failed",
            indicator=name,
            symbol=symbol,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return error_result(name, error_class=type(exc).__name__)
    except Exception as exc:
        # Catch-all: we MUST NOT let one indicator explode the whole
        # batch. Log + return an error result and continue.
        logger.exception(
            "indicator_compute_unexpected",
            indicator=name,
            symbol=symbol,
            error_type=type(exc).__name__,
        )
        return error_result(name, error_class=type(exc).__name__)

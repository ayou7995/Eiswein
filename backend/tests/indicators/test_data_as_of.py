"""Data-provenance honesty (data_as_of) across all indicators.

The architectural property under test: every indicator that consumes a
frame propagates ``frame.index[-1].date()`` as ``data_as_of`` on the
result. Cross-source consumers (relative_strength, rsp_spy, hyg_ief,
vix_term, yield_spread) propagate the **min** across their inputs.

These tests guard against the silent regression where a future indicator
forgets to plumb data_as_of through, which would re-introduce the bug
that motivated this work (FRED publication lag silently attributing
yesterday's data to today).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators._helpers import frame_as_of
from app.indicators.context import IndicatorContext
from app.indicators.direction.cho import compute_cho
from app.indicators.direction.price_vs_ma import compute_price_vs_ma
from app.indicators.direction.relative_strength import compute_relative_strength
from app.indicators.direction.rsi import compute_rsi
from app.indicators.direction.volume_anomaly import compute_volume_anomaly
from app.indicators.macro.dxy import compute_dxy
from app.indicators.macro.fed_rate import compute_fed_rate
from app.indicators.market_regime.ad_day import compute_ad_day
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

# --- frame_as_of helper -----------------------------------------------------


def test_frame_as_of_returns_last_index_date() -> None:
    idx = pd.date_range("2026-06-01", periods=5, freq="B")
    frame = pd.DataFrame({"x": range(5)}, index=idx)
    assert frame_as_of(frame) == date(2026, 6, 5)


def test_frame_as_of_returns_none_for_empty() -> None:
    assert frame_as_of(pd.DataFrame()) is None
    assert frame_as_of(None) is None


def test_frame_as_of_handles_non_timestamp_index() -> None:
    # A plain int-indexed frame can't have a date — should return None.
    frame = pd.DataFrame({"x": [1, 2, 3]})
    assert frame_as_of(frame) is None


# --- Per-ticker indicators (frame-only) ------------------------------------


def _ohlcv(close: np.ndarray, *, start: str = "2024-01-01") -> pd.DataFrame:
    n = len(close)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000_000, dtype="int64"),
        },
        index=idx,
    )


def _ctx() -> IndicatorContext:
    return IndicatorContext(today=date(2026, 6, 6))


def test_price_vs_ma_propagates_data_as_of() -> None:
    frame = _ohlcv(np.full(250, 100.0))
    result = compute_price_vs_ma(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_rsi_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_rsi(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_volume_anomaly_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_volume_anomaly(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_macd_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_macd(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_bollinger_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_bollinger(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_adx_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_adx(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_atr_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_atr(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_ttm_squeeze_propagates_data_as_of() -> None:
    rng = np.random.default_rng(seed=42)
    frame = _ohlcv(100.0 + rng.normal(0, 0.5, size=100).cumsum())
    result = compute_ttm_squeeze(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


def test_cho_propagates_data_as_of() -> None:
    frame = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1)
    result = compute_cho(frame, _ctx())
    assert result.data_as_of == frame.index[-1].date()


# --- Cross-source: relative_strength uses min(ticker, spx) ------------------


def test_relative_strength_propagates_min_of_ticker_and_spx() -> None:
    # Ticker has data through 6/6; SPX only through 6/4 (FRED-style lag).
    ticker = _ohlcv(100.0 + np.arange(60, dtype="float64") * 0.1, start="2024-04-01")
    spx_short = _ohlcv(400.0 + np.arange(58, dtype="float64") * 0.1, start="2024-04-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), spx_frame=spx_short)
    result = compute_relative_strength(ticker, ctx)
    # Should be the EARLIER of the two — the SPX-frame's last date.
    assert result.data_as_of == spx_short.index[-1].date()


# --- Market regime SPX-based -----------------------------------------------


def test_spx_ma_propagates_spx_frame_as_of() -> None:
    spx = _ohlcv(400.0 + np.arange(250, dtype="float64") * 0.1)
    ctx = IndicatorContext(today=date(2026, 6, 6), spx_frame=spx)
    result = compute_spx_ma(spx, ctx)
    assert result.data_as_of == spx.index[-1].date()


def test_spx_adx_propagates_spx_frame_as_of() -> None:
    spx = _ohlcv(400.0 + np.arange(80, dtype="float64") * 0.1)
    ctx = IndicatorContext(today=date(2026, 6, 6), spx_frame=spx)
    result = compute_spx_adx(pd.DataFrame(), ctx)
    assert result.data_as_of == spx.index[-1].date()


def test_ad_day_propagates_spx_frame_as_of() -> None:
    spx = _ohlcv(400.0 + np.arange(40, dtype="float64") * 0.1)
    ctx = IndicatorContext(today=date(2026, 6, 6), spx_frame=spx)
    result = compute_ad_day(spx, ctx)
    assert result.data_as_of == spx.index[-1].date()


# --- FRED-based (the actual cause of the original bug) ---------------------


def _macro(values: list[float], *, start: str = "2026-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"value": values}, index=idx)


def test_vix_propagates_macro_frame_as_of_NOT_today() -> None:
    """The actual bug we're fixing. The FRED VIXCLS frame only has data
    through 6/4 but the snapshot ``today`` is 6/6. The result MUST
    carry data_as_of = 6/4 (the FRED date), NOT 6/6 (the snapshot)."""
    vix_frame = _macro([15.0] * 20, start="2026-05-08")  # ends ~2026-06-04
    expected = vix_frame.index[-1].date()
    ctx = IndicatorContext(today=date(2026, 6, 6), macro_frames={"VIXCLS": vix_frame})
    result = compute_vix(pd.DataFrame(), ctx)
    assert result.data_as_of == expected
    assert result.data_as_of < date(2026, 6, 6)  # the snapshot date


def test_vix_term_propagates_min_of_vixcls_and_vxvcls() -> None:
    # VIXCLS fresher than VXVCLS — should pick the earlier of the two.
    vix_long = _macro([15.0] * 30, start="2026-05-01")  # ends later
    vix3m_short = _macro([18.0] * 25, start="2026-05-01")  # ends earlier
    ctx = IndicatorContext(
        today=date(2026, 6, 6),
        macro_frames={"VIXCLS": vix_long, "VXVCLS": vix3m_short},
    )
    result = compute_vix_term(pd.DataFrame(), ctx)
    assert result.data_as_of == vix3m_short.index[-1].date()


def test_yield_spread_propagates_min_of_dgs10_and_dgs2() -> None:
    ten_long = _macro([4.5] * 30, start="2026-05-01")
    two_short = _macro([4.0] * 25, start="2026-05-01")
    ctx = IndicatorContext(
        today=date(2026, 6, 6),
        macro_frames={"DGS10": ten_long, "DGS2": two_short},
    )
    result = compute_yield_spread(pd.DataFrame(), ctx)
    assert result.data_as_of == two_short.index[-1].date()


def test_dxy_propagates_weekly_frame_as_of() -> None:
    """DXY uses DTWEXBGS which FRED publishes WEEKLY — data_as_of should
    correctly track that the latest value is days/weeks old."""
    # DTWEXBGS sample: data ending 5/29 (a Friday)
    dxy_frame = _macro([118.0] * 30, start="2026-04-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), macro_frames={"DTWEXBGS": dxy_frame})
    result = compute_dxy(pd.DataFrame(), ctx)
    assert result.data_as_of == dxy_frame.index[-1].date()
    # Confirm the lag is reflected.
    assert (date(2026, 6, 6) - result.data_as_of).days > 0


def test_fed_rate_propagates_monthly_frame_as_of() -> None:
    fed_frame = _macro([3.5] * 10, start="2025-09-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), macro_frames={"FEDFUNDS": fed_frame})
    result = compute_fed_rate(pd.DataFrame(), ctx)
    assert result.data_as_of == fed_frame.index[-1].date()




# --- rsp_spy / hyg_ief: cross-source min ----------------------------------


def test_rsp_spy_propagates_min_of_spy_and_rsp() -> None:
    from app.indicators.market_regime.rsp_spy import compute_rsp_spy
    spy_long = _ohlcv(400.0 + np.arange(40, dtype="float64") * 0.5, start="2026-04-01")
    rsp_short = _ohlcv(200.0 + np.arange(30, dtype="float64") * 0.7, start="2026-04-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), spx_frame=spy_long, rsp_frame=rsp_short)
    result = compute_rsp_spy(None, ctx)
    assert result.data_as_of == rsp_short.index[-1].date()


def test_hyg_ief_propagates_min_of_hyg_and_ief() -> None:
    from app.indicators.market_regime.hyg_ief import compute_hyg_ief
    hyg_long = _ohlcv(80.0 + np.arange(40, dtype="float64") * 0.1, start="2026-04-01")
    ief_short = _ohlcv(np.full(30, 95.0), start="2026-04-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), hyg_frame=hyg_long, ief_frame=ief_short)
    result = compute_hyg_ief(None, ctx)
    assert result.data_as_of == ief_short.index[-1].date()


def test_skew_propagates_skew_frame_as_of() -> None:
    from app.indicators.market_regime.skew import compute_skew
    skew_frame = _ohlcv(np.full(20, 120.0), start="2026-05-01")
    ctx = IndicatorContext(today=date(2026, 6, 6), skew_frame=skew_frame)
    result = compute_skew(None, ctx)
    assert result.data_as_of == skew_frame.index[-1].date()


def test_unrate_propagates_macro_frame_as_of() -> None:
    """UNRATE monthly publication lag flows through honestly — FRED's
    latest UNRATE observation is at least a few weeks behind ``today``."""
    from app.indicators.market_regime.unrate import compute_unrate
    monthly_idx = pd.date_range("2025-01-01", periods=15, freq="MS")
    unrate_frame = pd.DataFrame({"value": [3.7] * 15}, index=monthly_idx)
    ctx = IndicatorContext(today=date(2026, 6, 6), macro_frames={"UNRATE": unrate_frame})
    result = compute_unrate(None, ctx)
    assert result.data_as_of == unrate_frame.index[-1].date()
    assert (date(2026, 6, 6) - result.data_as_of).days > 0

"""Layer 1 market posture classifier."""

from __future__ import annotations

from app.indicators.base import SignalTone
from app.signals.market_posture import classify_market_posture, count_regime_tones
from app.signals.types import MarketPosture
from tests.signals.conftest import _make_result, build_regime_results


def test_market_posture_3_green_is_offensive() -> None:
    results = build_regime_results(3, 0)
    assert classify_market_posture(results) == MarketPosture.OFFENSIVE


def test_market_posture_4_green_is_offensive() -> None:
    results = build_regime_results(4, 0)
    assert classify_market_posture(results) == MarketPosture.OFFENSIVE


def test_market_posture_2_red_is_defensive() -> None:
    results = build_regime_results(0, 2)
    assert classify_market_posture(results) == MarketPosture.DEFENSIVE


def test_market_posture_3_red_is_defensive() -> None:
    results = build_regime_results(0, 3)
    assert classify_market_posture(results) == MarketPosture.DEFENSIVE


def test_market_posture_2_green_2_yellow_is_normal() -> None:
    results = build_regime_results(2, 0, yellows=2)
    assert classify_market_posture(results) == MarketPosture.NORMAL


def test_market_posture_all_yellow_is_normal() -> None:
    results = build_regime_results(0, 0, yellows=4)
    assert classify_market_posture(results) == MarketPosture.NORMAL


def test_market_posture_all_insufficient_is_normal() -> None:
    """Safe default when no regime indicator has sufficient data."""
    results = {
        name: _make_result(name, data_sufficient=False)
        for name in ("spx_ma", "ad_day", "vix", "yield_spread")
    }
    assert classify_market_posture(results) == MarketPosture.NORMAL


def test_count_regime_tones_excludes_insufficient() -> None:
    results = build_regime_results(2, 1, yellows=1)
    g, r, y = count_regime_tones(results)
    assert (g, r, y) == (2, 1, 1)


def test_count_regime_tones_ignores_non_regime_indicators() -> None:
    results = build_regime_results(3, 0)
    results["macd"] = _make_result("macd", SignalTone.RED)
    g, r, y = count_regime_tones(results)
    assert g == 3
    assert r == 0

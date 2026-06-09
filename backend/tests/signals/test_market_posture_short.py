"""Layer 1-short — Short-term market posture classifier (4-vote)."""

from __future__ import annotations

from app.indicators.base import IndicatorResult, SignalTone, SignalToneLiteral
from app.signals.market_posture_short import (
    REGIME_SHORT_INDICATOR_NAMES,
    classify_market_posture_short,
    count_regime_short_tones,
)
from app.signals.types import MarketPosture
from tests.signals.conftest import _make_result


def _build_short(greens: int, reds: int, yellows: int = 0) -> dict[str, IndicatorResult]:
    """Construct a 4-indicator short-regime dict."""
    names = ["vix", "ad_day", "vix_term", "skew"]
    if greens + reds + yellows > 4:
        msg = "green + red + yellow votes exceed 4"
        raise ValueError(msg)
    signals: list[SignalToneLiteral] = (
        [SignalTone.GREEN] * greens
        + [SignalTone.RED] * reds
        + [SignalTone.YELLOW] * yellows
    )
    while len(signals) < 4:
        signals.append(SignalTone.YELLOW)
    return {name: _make_result(name, sig) for name, sig in zip(names, signals, strict=True)}


def test_regime_short_indicator_names_includes_skew() -> None:
    assert "skew" in REGIME_SHORT_INDICATOR_NAMES
    assert frozenset({"vix", "ad_day", "vix_term", "skew"}) == REGIME_SHORT_INDICATOR_NAMES


def test_short_posture_4_green_is_offensive() -> None:
    """All 4 must agree to declare OFFENSIVE on a tactical horizon."""
    assert classify_market_posture_short(_build_short(4, 0)) == MarketPosture.OFFENSIVE


def test_short_posture_3_green_is_normal() -> None:
    """3/4 GREEN is not enough — slow to declare safety."""
    assert classify_market_posture_short(_build_short(3, 0)) == MarketPosture.NORMAL


def test_short_posture_1_red_is_normal() -> None:
    """4-vote relaxed the prior 1+ RED rule to 2+ RED (less noisy)."""
    assert classify_market_posture_short(_build_short(0, 1)) == MarketPosture.NORMAL


def test_short_posture_2_red_is_defensive() -> None:
    assert classify_market_posture_short(_build_short(0, 2)) == MarketPosture.DEFENSIVE


def test_short_posture_4_red_is_defensive() -> None:
    assert classify_market_posture_short(_build_short(0, 4)) == MarketPosture.DEFENSIVE


def test_short_posture_all_yellow_is_normal() -> None:
    assert classify_market_posture_short(_build_short(0, 0, yellows=4)) == MarketPosture.NORMAL


def test_short_posture_all_insufficient_is_normal() -> None:
    results = {
        name: _make_result(name, data_sufficient=False)
        for name in REGIME_SHORT_INDICATOR_NAMES
    }
    assert classify_market_posture_short(results) == MarketPosture.NORMAL


def test_count_regime_short_tones_excludes_insufficient() -> None:
    results = _build_short(2, 1, yellows=1)
    g, r, y = count_regime_short_tones(results)
    assert (g, r, y) == (2, 1, 1)


def test_count_regime_short_tones_ignores_non_short_indicators() -> None:
    results = _build_short(3, 0)
    results["macd"] = _make_result("macd", SignalTone.RED)
    g, r, y = count_regime_short_tones(results)
    assert g == 3
    assert r == 0

"""VIX Term Structure — spot vs 3M ratio classifier (v2 Phase 4)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.vix_term import compute_vix_term


def _macro_frame(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.DataFrame({"value": values}, index=idx)


def _ctx(vix: list[float] | None, vix3m: list[float] | None) -> IndicatorContext:
    macro: dict[str, pd.DataFrame] = {}
    if vix is not None:
        macro["VIXCLS"] = _macro_frame(vix)
    if vix3m is not None:
        macro["VXVCLS"] = _macro_frame(vix3m)
    return IndicatorContext(today=date(2026, 6, 5), macro_frames=macro)


def test_vix_term_insufficient_when_either_series_missing() -> None:
    assert compute_vix_term(None, _ctx(None, None)).data_sufficient is False
    assert compute_vix_term(None, _ctx([15.0] * 10, None)).data_sufficient is False
    assert compute_vix_term(None, _ctx(None, [18.0] * 10)).data_sufficient is False


def test_vix_term_deep_contango_is_green() -> None:
    """VIX 13 / VIX3M 17 → ratio ≈ 0.76 ≪ 0.95 → GREEN."""
    result = compute_vix_term(None, _ctx([13.0] * 10, [17.0] * 10))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "contango" in result.short_label
    assert result.detail["ratio"] < 0.95


def test_vix_term_flat_is_yellow() -> None:
    """VIX 17 / VIX3M 18 → ratio ≈ 0.94. Right at the contango boundary; 0.94 < 0.95 = GREEN."""
    result = compute_vix_term(None, _ctx([16.5] * 10, [17.0] * 10))
    # 16.5/17 = 0.97 → YELLOW
    assert result.signal == SignalTone.YELLOW
    assert "平坦" in result.short_label


def test_vix_term_inversion_is_red() -> None:
    """VIX 32 / VIX3M 28 → ratio > 1 → RED (curve inverted, panic)."""
    result = compute_vix_term(None, _ctx([32.0] * 10, [28.0] * 10))
    assert result.signal == SignalTone.RED
    assert "倒掛" in result.short_label
    assert result.detail["ratio"] >= 1.0


def test_vix_term_detail_keys_present() -> None:
    result = compute_vix_term(None, _ctx([15.0] * 10, [18.0] * 10))
    assert {"vix", "vix3m", "ratio", "contango_threshold", "inversion_threshold"}.issubset(
        result.detail.keys()
    )

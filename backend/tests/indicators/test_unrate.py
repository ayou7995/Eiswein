"""US unemployment + Sahm Rule recession trigger."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.indicators.base import SignalTone
from app.indicators.context import IndicatorContext
from app.indicators.market_regime.unrate import compute_unrate


def _unrate_frame(values: list[float], *, start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"value": values}, index=idx)


def _ctx(unrate: pd.DataFrame | None) -> IndicatorContext:
    macro = {"UNRATE": unrate} if unrate is not None else {}
    return IndicatorContext(today=date(2026, 6, 1), macro_frames=macro)


def test_unrate_insufficient_when_missing() -> None:
    assert compute_unrate(None, _ctx(None)).data_sufficient is False


def test_unrate_insufficient_when_fewer_than_13_months() -> None:
    result = compute_unrate(None, _ctx(_unrate_frame([3.5] * 8)))
    assert result.data_sufficient is False


def test_unrate_stable_low_is_green() -> None:
    # 24 months hovering 3.5-3.7%; 12M low 3.5; 3MMA ≈ 3.6; Sahm ≈ 0.1.
    values = [
        *[3.5, 3.6, 3.7, 3.5, 3.6, 3.5, 3.5, 3.6, 3.5, 3.6, 3.5, 3.5],
        *[3.6, 3.5, 3.6, 3.6, 3.6, 3.6, 3.6, 3.5, 3.6, 3.7, 3.5, 3.6],
    ]
    result = compute_unrate(None, _ctx(_unrate_frame(values)))
    assert result.data_sufficient is True
    assert result.signal == SignalTone.GREEN
    assert "健康" in result.short_label


def test_unrate_warning_zone_is_yellow() -> None:
    # 12 months at 3.5; last 12 climb 3.6 → 4.0. Last 12 low = 3.6,
    # last 3 mean = 4.0 → Sahm = 0.4 (between 0.30 warning and 0.50 trigger).
    base = [3.5] * 12
    tail = [3.6, 3.7, 3.7, 3.8, 3.8, 3.8, 3.9, 3.9, 3.9, 4.0, 4.0, 4.0]
    values = base + tail
    result = compute_unrate(None, _ctx(_unrate_frame(values)))
    assert result.signal == SignalTone.YELLOW
    assert "警戒" in result.short_label


def test_unrate_sahm_triggered_is_red() -> None:
    # First 12 around 3.5; last 12 climbing to 4.5+ → 3MMA ≈ 4.4; low 3.5;
    # Sahm ≈ 0.9 → above 0.5 trigger.
    base = [3.5] * 12
    tail = [3.6, 3.7, 3.8, 3.9, 4.0, 4.1, 4.2, 4.3, 4.4, 4.5, 4.4, 4.4]
    values = base + tail
    result = compute_unrate(None, _ctx(_unrate_frame(values)))
    assert result.signal == SignalTone.RED
    assert "衰退訊號" in result.short_label


def test_unrate_detail_keys_present() -> None:
    values = list(np.linspace(3.5, 3.6, 24))
    result = compute_unrate(None, _ctx(_unrate_frame(values)))
    keys = {
        "current_rate",
        "prior_month_rate",
        "three_month_avg",
        "twelve_month_low",
        "sahm_value",
        "sahm_distance_to_trigger",
        "threshold_warning",
        "threshold_trigger",
    }
    assert keys.issubset(result.detail.keys())


def test_unrate_propagates_data_as_of() -> None:
    frame = _unrate_frame([3.5] * 24, start="2024-01-01")
    result = compute_unrate(None, _ctx(frame))
    assert result.data_as_of == frame.index[-1].date()

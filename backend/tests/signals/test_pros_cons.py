"""Pros/Cons structured list builder — mapping + no-template guarantee."""

from __future__ import annotations

from app.indicators.base import SignalTone
from app.signals.pros_cons import build_pros_cons_items
from tests.signals.conftest import _make_result


def test_pros_cons_maps_signals_correctly() -> None:
    """GREEN → pro, RED → con, YELLOW → neutral, insufficient → neutral."""
    results = {
        "price_vs_ma": _make_result("price_vs_ma", SignalTone.GREEN, short_label="多頭"),
        "rsi": _make_result("rsi", SignalTone.RED, short_label="超賣"),
        "volume_anomaly": _make_result("volume_anomaly", SignalTone.YELLOW, short_label="量能平淡"),
        "relative_strength": _make_result(
            "relative_strength", data_sufficient=False, short_label="資料不足"
        ),
    }
    items = build_pros_cons_items(results)
    tones = {i.indicator_name: i.tone for i in items}
    assert tones == {
        "price_vs_ma": "pro",
        "rsi": "con",
        "volume_anomaly": "neutral",
        "relative_strength": "neutral",
    }


def test_pros_cons_categorizes_by_indicator_name() -> None:
    """direction / timing / macro buckets are mapped from indicator_name."""
    results = {
        "price_vs_ma": _make_result("price_vs_ma", SignalTone.GREEN),
        "macd": _make_result("macd", SignalTone.GREEN),
        "dxy": _make_result("dxy", SignalTone.RED),
        "spx_ma": _make_result("spx_ma", SignalTone.YELLOW),
        "ad_day": _make_result("ad_day", SignalTone.GREEN),
    }
    items = build_pros_cons_items(results)
    by_name = {i.indicator_name: i for i in items}

    assert by_name["price_vs_ma"].category == "direction"
    assert by_name["macd"].category == "timing"
    assert by_name["dxy"].category == "macro"
    # Regime indicators surface under "macro" at the domain layer — the
    # frontend re-buckets spx_ma/ad_day/vix/yield_spread under 大盤 visually.
    assert by_name["spx_ma"].category == "macro"
    assert by_name["ad_day"].category == "macro"


def test_pros_cons_has_no_prose_in_short_labels() -> None:
    """The builder must NOT concatenate, template, or generate prose.

    The short_label on each item must equal the IndicatorResult's
    short_label byte-for-byte.
    """
    label = "RSI 中性 55 (測試字串)"
    results = {"rsi": _make_result("rsi", SignalTone.YELLOW, short_label=label)}
    items = build_pros_cons_items(results)
    assert len(items) == 1
    assert items[0].short_label == label


def test_pros_cons_skips_unknown_indicator_names() -> None:
    """Unknown name → skipped (keeps list coherent when new indicators land)."""
    results = {
        "rsi": _make_result("rsi", SignalTone.GREEN),
        "future_indicator": _make_result("future_indicator", SignalTone.GREEN),
    }
    items = build_pros_cons_items(results)
    names = {i.indicator_name for i in items}
    assert "rsi" in names
    assert "future_indicator" not in names


def test_pros_cons_preserves_detail_dict() -> None:
    detail = {"ma50": 150.0, "ma200": 140.0, "price_vs_ma50_pct": 1.2}
    results = {
        "price_vs_ma": _make_result(
            "price_vs_ma", SignalTone.GREEN, short_label="多頭", detail=detail
        )
    }
    items = build_pros_cons_items(results)
    assert items[0].detail == detail


def test_pros_cons_items_are_frozen_dataclass() -> None:
    import dataclasses

    import pytest

    results = {"rsi": _make_result("rsi", SignalTone.GREEN)}
    items = build_pros_cons_items(results)
    with pytest.raises(dataclasses.FrozenInstanceError):
        items[0].tone = "con"  # type: ignore[misc]


def test_pros_cons_emits_timeframe_for_every_known_indicator() -> None:
    """Every indicator in INDICATOR_TIMEFRAMES must produce a valid
    short / mid / long timeframe on its emitted item.
    """
    from app.indicators.timeframes import INDICATOR_TIMEFRAMES

    results = {
        name: _make_result(name, SignalTone.GREEN)
        for name in INDICATOR_TIMEFRAMES
    }
    items = build_pros_cons_items(results)

    by_name = {item.indicator_name: item for item in items}
    # Every mapped indicator surfaces an item.
    assert set(by_name.keys()) == set(INDICATOR_TIMEFRAMES.keys())
    # Each item carries the expected timeframe value.
    for name, expected_tf in INDICATOR_TIMEFRAMES.items():
        assert by_name[name].timeframe == expected_tf, (
            f"{name} timeframe drift: expected {expected_tf}, "
            f"got {by_name[name].timeframe}"
        )
    # Sanity: only the three allowed values appear.
    assert {item.timeframe for item in items} <= {"short", "mid", "long"}

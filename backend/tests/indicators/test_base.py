"""Base types: IndicatorResult is frozen, version is semver, helpers work."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.indicators.base import (
    INDICATOR_VERSION,
    IndicatorResult,
    SignalTone,
    error_result,
    insufficient_result,
)


def test_indicator_version_is_semver() -> None:
    assert re.match(r"^\d+\.\d+\.\d+$", INDICATOR_VERSION)


def test_indicator_result_is_frozen() -> None:
    result = IndicatorResult(
        name="test",
        value=1.0,
        signal=SignalTone.GREEN,
        data_sufficient=True,
        short_label="測試",
        detail={},
        computed_at=datetime.now(UTC),
    )
    # Pydantic v2 raises ValidationError on frozen-model mutation.
    with pytest.raises(ValidationError):
        result.value = 2.0  # type: ignore[misc]


def test_insufficient_result_is_neutral_and_has_chinese_label() -> None:
    result = insufficient_result("rsi")
    assert result.data_sufficient is False
    assert result.signal == SignalTone.NEUTRAL
    assert result.value is None
    # Traditional Chinese characters present.
    assert any("\u4e00" <= ch <= "\u9fff" for ch in result.short_label)


def test_error_result_captures_class_only_not_message() -> None:
    result = error_result("rsi", error_class="ZeroDivisionError")
    assert result.data_sufficient is False
    assert result.signal == SignalTone.NEUTRAL
    assert result.detail["error_class"] == "ZeroDivisionError"
    # No raw exception message — those stay in structured logs, not the DB
    # detail dict or the API response (per security-auditor findings).
    assert "error" not in result.detail


def test_signal_tone_constants_are_literal_strings() -> None:
    assert SignalTone.GREEN == "green"
    assert SignalTone.YELLOW == "yellow"
    assert SignalTone.RED == "red"
    assert SignalTone.NEUTRAL == "neutral"

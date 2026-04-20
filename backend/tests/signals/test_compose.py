"""Compose + should_show_timing rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.signals.compose import compose_signal, should_show_timing
from app.signals.types import (
    ActionCategory,
    EntryTiers,
    MarketPosture,
    TimingModifier,
)


@pytest.mark.parametrize(
    ("action", "expected_show"),
    [
        (ActionCategory.STRONG_BUY, True),
        (ActionCategory.BUY, True),
        (ActionCategory.HOLD, True),
        (ActionCategory.WATCH, False),
        (ActionCategory.REDUCE, False),
        (ActionCategory.EXIT, False),
    ],
)
def test_should_show_timing_only_buy_side(action: ActionCategory, expected_show: bool) -> None:
    """D1b: timing modifier surfaces only for buy-side actions."""
    assert should_show_timing(action) is expected_show


def test_compose_suppresses_timing_for_exit_side() -> None:
    """EXIT action → show_timing_modifier=False regardless of timing value."""
    tiers = EntryTiers(aggressive=Decimal("100"), ideal=None, conservative=None)
    sig = compose_signal(
        symbol="AAPL",
        trade_date=date(2024, 12, 31),
        action=ActionCategory.EXIT,
        direction_green_count=0,
        direction_red_count=4,
        timing_modifier=TimingModifier.FAVORABLE,  # pretend timing is good
        market_posture=MarketPosture.DEFENSIVE,
        entry_tiers=tiers,
        stop_loss=Decimal("95"),
    )
    assert sig.action == ActionCategory.EXIT
    assert sig.show_timing_modifier is False
    # Timing modifier value is preserved for audit; only the flag is False.
    assert sig.timing_modifier == TimingModifier.FAVORABLE


def test_compose_shows_timing_for_strong_buy() -> None:
    tiers = EntryTiers(aggressive=Decimal("100"), ideal=None, conservative=None)
    sig = compose_signal(
        symbol="AAPL",
        trade_date=date(2024, 12, 31),
        action=ActionCategory.STRONG_BUY,
        direction_green_count=4,
        direction_red_count=0,
        timing_modifier=TimingModifier.FAVORABLE,
        market_posture=MarketPosture.OFFENSIVE,
        entry_tiers=tiers,
        stop_loss=Decimal("90"),
    )
    assert sig.show_timing_modifier is True


def test_compose_output_is_frozen() -> None:
    """ComposedSignal is immutable (rule 11)."""
    from pydantic import ValidationError

    tiers = EntryTiers(aggressive=None, ideal=None, conservative=None)
    sig = compose_signal(
        symbol="AAPL",
        trade_date=date(2024, 12, 31),
        action=ActionCategory.HOLD,
        direction_green_count=2,
        direction_red_count=0,
        timing_modifier=TimingModifier.MIXED,
        market_posture=MarketPosture.NORMAL,
        entry_tiers=tiers,
        stop_loss=None,
    )
    with pytest.raises(ValidationError):
        sig.action = ActionCategory.BUY  # type: ignore[misc]

"""Chinese label table tests."""

from __future__ import annotations

from app.signals.labels import (
    ACTION_LABELS,
    POSTURE_LABELS,
    TIMING_BADGES,
    posture_streak_badge,
)
from app.signals.types import ActionCategory, MarketPosture, TimingModifier


def test_action_labels_cover_all_enum_members() -> None:
    assert set(ACTION_LABELS.keys()) == set(ActionCategory)


def test_timing_badges_cover_all_enum_members() -> None:
    assert set(TIMING_BADGES.keys()) == set(TimingModifier)


def test_timing_mixed_has_no_badge() -> None:
    assert TIMING_BADGES[TimingModifier.MIXED] is None


def test_posture_labels_cover_all_enum_members() -> None:
    assert set(POSTURE_LABELS.keys()) == set(MarketPosture)


def test_posture_streak_badge_below_threshold_is_none() -> None:
    assert posture_streak_badge(MarketPosture.OFFENSIVE, streak_days=1) is None
    assert posture_streak_badge(MarketPosture.OFFENSIVE, streak_days=2) is None


def test_posture_streak_badge_offensive_3_days_has_badge() -> None:
    badge = posture_streak_badge(MarketPosture.OFFENSIVE, streak_days=3)
    assert badge is not None
    assert "3" in badge
    assert "進攻" in badge


def test_posture_streak_badge_normal_has_no_badge() -> None:
    assert posture_streak_badge(MarketPosture.NORMAL, streak_days=10) is None


def test_posture_streak_badge_defensive_has_badge() -> None:
    badge = posture_streak_badge(MarketPosture.DEFENSIVE, streak_days=5)
    assert badge is not None
    assert "防守" in badge

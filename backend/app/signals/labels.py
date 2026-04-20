"""Human-readable Chinese labels for signal enums.

Split out from :mod:`app.signals.types` so consumers that only need
the enums (DB rows, tests) don't pull the label table — and so the
label table stays in one place for the API-layer Chinese string use.

UI strings are Traditional Chinese per the project language rule
(``CLAUDE.md``). Identifiers stay English.
"""

from __future__ import annotations

from app.signals.types import ActionCategory, MarketPosture, TimingModifier

ACTION_LABELS: dict[ActionCategory, str] = {
    ActionCategory.STRONG_BUY: "強力買入 🟢🟢",
    ActionCategory.BUY: "買入 🟢",
    ActionCategory.HOLD: "持有 ✓",
    ActionCategory.WATCH: "觀望 👀",
    ActionCategory.REDUCE: "減倉 ⚠️",
    ActionCategory.EXIT: "出場 🔴🔴",
}


# Timing badge is ``None`` for the "mixed" case: D1b says no badge is
# rendered, not an empty badge. The frontend uses ``None`` to decide
# whether to emit the ``<span>`` at all.
TIMING_BADGES: dict[TimingModifier, str | None] = {
    TimingModifier.FAVORABLE: "✓ 時機好",
    TimingModifier.MIXED: None,
    TimingModifier.UNFAVORABLE: "⏳ 等回調",
}


POSTURE_LABELS: dict[MarketPosture, str] = {
    MarketPosture.OFFENSIVE: "進攻",
    MarketPosture.NORMAL: "正常",
    MarketPosture.DEFENSIVE: "防守",
}


INSUFFICIENT_DATA_NOTE = "⚪ 資料不足以判斷"


def posture_streak_badge(posture: MarketPosture, streak_days: int) -> str | None:
    """Produce the dashboard streak badge or ``None`` below threshold.

    D3 specifies badges only for streaks of 3+ days, and only on the
    OFFENSIVE / DEFENSIVE postures (NORMAL is implicitly the baseline).
    """
    if streak_days < 3:
        return None
    if posture is MarketPosture.OFFENSIVE:
        return f"進攻 {streak_days} 天 ✨"
    if posture is MarketPosture.DEFENSIVE:
        return f"防守 {streak_days} 天"
    return None

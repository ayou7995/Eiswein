"""Public types for the signal composition layer (Phase 3).

Covers:
* ``ActionCategory`` — D1a output (強力買入 / 買入 / 持有 / 觀望 / 減倉 / 出場).
* ``TimingModifier`` — D1b output (✓ 時機好 / mixed / ⏳ 等回調).
* ``MarketPosture`` — market-regime gate (進攻 / 正常 / 防守).
* ``EntryTiers`` — 3-tier entry price suggestions (aggressive/ideal/conservative).
* ``ComposedSignal`` — the immutable final record assembled by ``compose.py``.
* ``ProsConsItem`` — scannable Pros/Cons UI entry per indicator.

Design notes
------------
* ``ActionCategory``/``TimingModifier``/``MarketPosture`` are ``str, Enum``
  subclasses so Pydantic serializes them as short stable strings
  (``"strong_buy"`` etc.) matching the SQLite ``VARCHAR(20)`` columns.
* ``ComposedSignal``/``EntryTiers`` are frozen so callers that hold a
  reference can't mutate it after persistence.
* Decimals on entry/stop-loss preserve exact round-tripping between
  API response and DB storage (same pattern as DailyPrice).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ActionCategory(str, Enum):
    """D1a: 6-way direction classification."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    WATCH = "watch"
    REDUCE = "reduce"
    EXIT = "exit"


class TimingModifier(str, Enum):
    """D1b: 3-way timing modifier."""

    FAVORABLE = "favorable"
    MIXED = "mixed"
    UNFAVORABLE = "unfavorable"


class MarketPosture(str, Enum):
    """Layer 1: 3-way market-regime posture (進攻 / 正常 / 防守)."""

    OFFENSIVE = "offensive"
    NORMAL = "normal"
    DEFENSIVE = "defensive"


# ---- Pros/Cons -----------------------------------------------------------

ProsConsToneLiteral = Literal["pro", "con", "neutral"]
ProsConsCategoryLiteral = Literal["direction", "timing", "macro", "risk"]


@dataclass(frozen=True, slots=True)
class ProsConsItem:
    """Single scannable UI entry derived from an :class:`IndicatorResult`.

    UX rule (``CLAUDE.md``): we MUST NOT build prose from indicator
    results. Each item surfaces the verbatim ``short_label`` plus the
    structured ``detail`` so the frontend can render a single bullet
    with expand-on-tap behaviour.
    """

    category: ProsConsCategoryLiteral
    tone: ProsConsToneLiteral
    short_label: str
    detail: dict[str, Any]
    indicator_name: str


# ---- Entry tiers / Composed signal ---------------------------------------


class EntryTiers(BaseModel):
    """Three-tier entry price suggestion (I15).

    ``aggressive`` tracks the 50MA (short-term support), ``ideal`` tracks
    the 20MA / Bollinger middle, ``conservative`` tracks the 200MA
    (or Bollinger lower when below 200MA).

    ``split_suggestion`` is a display-only hint — the frontend labels it
    ``僅供參考`` (reference only, not a trade instruction).
    """

    model_config = ConfigDict(frozen=True)

    aggressive: Decimal | None
    ideal: Decimal | None
    conservative: Decimal | None
    split_suggestion: tuple[int, int, int] = (30, 40, 30)


class ComposedSignal(BaseModel):
    """Immutable composed per-ticker signal snapshot for day ``date``.

    One ``ComposedSignal`` corresponds to one ``TickerSnapshot`` DB row
    after persistence; the in-memory type is the domain-layer record,
    while the SQL row is the infrastructure-layer projection.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    date: date
    action: ActionCategory
    direction_green_count: int
    direction_red_count: int
    timing_modifier: TimingModifier
    show_timing_modifier: bool
    entry_tiers: EntryTiers
    stop_loss: Decimal | None
    market_posture_at_compute: MarketPosture
    indicator_version: str
    computed_at: datetime

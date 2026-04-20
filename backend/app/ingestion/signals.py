"""Signal composition persistence layer (Phase 3).

After ``compute_and_persist`` (Phase 2) has stored per-indicator
DailySignal rows for a ticker, this module assembles the composite
``TickerSnapshot`` row using the already-in-memory IndicatorResult
dict. We deliberately pass the in-memory dict rather than re-reading
DailySignal rows — this avoids a DB round-trip and keeps the signal
layer free of DB-model coupling.

Functions:

* ``compose_and_persist_ticker`` — one ticker's snapshot.
* ``compose_and_persist_market`` — the global MarketSnapshot + streak.

Each function wraps its own try/except at the call-site in
``daily_ingestion`` (rule 14): one ticker's compose failure does not
abort the batch.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd
import structlog

from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.db.repositories.market_snapshot_repository import (
    MarketSnapshotRepository,
    build_market_snapshot_row,
)
from app.db.repositories.ticker_snapshot_repository import (
    TickerSnapshotRepository,
    composed_to_row,
)
from app.indicators.base import INDICATOR_VERSION, IndicatorResult
from app.signals.compose import compose_signal
from app.signals.direction import classify_direction
from app.signals.entry_price import compute_entry_tiers
from app.signals.market_posture import (
    classify_market_posture,
    count_regime_tones,
)
from app.signals.stop_loss import compute_stop_loss
from app.signals.timing import classify_timing
from app.signals.types import ComposedSignal, MarketPosture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.signals")


def compose_and_persist_ticker(
    symbol: str,
    trade_date: date,
    *,
    db: Session,
    per_ticker_results: dict[str, IndicatorResult],
    market_posture: MarketPosture,
) -> ComposedSignal | None:
    """Compose + persist a :class:`TickerSnapshot` for one ticker.

    Returns the composed signal on success, ``None`` when the ticker
    has no stored price frame (shouldn't happen after Phase 2 persist,
    but guarded for idempotency).
    """
    prices = DailyPriceRepository(db)
    price_frame = _load_price_frame(prices, symbol, trade_date)
    # We need SOME price frame to compute entry tiers + stop-loss. If
    # Phase 2 produced indicator results but DailyPrice is somehow
    # empty (shouldn't happen after Phase 2 persist) we still compose
    # but with None entry/stop tiers.
    action, green, red = classify_direction(per_ticker_results)
    timing = classify_timing(per_ticker_results)
    entry_tiers = compute_entry_tiers(
        price_frame if price_frame is not None else pd.DataFrame(),
        timing_modifier=timing,
    )
    stop_loss = compute_stop_loss(
        price_frame if price_frame is not None else pd.DataFrame(),
        direction_action=action,
    )

    signal = compose_signal(
        symbol=symbol.upper(),
        trade_date=trade_date,
        action=action,
        direction_green_count=green,
        direction_red_count=red,
        timing_modifier=timing,
        market_posture=market_posture,
        entry_tiers=entry_tiers,
        stop_loss=stop_loss,
        indicator_version=INDICATOR_VERSION,
    )

    repo = TickerSnapshotRepository(db)
    repo.upsert_many([composed_to_row(signal)])
    return signal


def compose_and_persist_market(
    trade_date: date,
    *,
    db: Session,
    regime_results: dict[str, IndicatorResult],
) -> MarketPosture:
    """Classify + persist the MarketSnapshot + update the streak row.

    Returns the posture so callers can reuse it for
    ``compose_and_persist_ticker`` (avoids re-classifying per ticker).
    """
    posture = classify_market_posture(regime_results)
    greens, reds, yellows = count_regime_tones(regime_results)
    computed_at = datetime.now(UTC)

    snap_row = build_market_snapshot_row(
        trade_date=trade_date,
        posture=posture,
        regime_green_count=greens,
        regime_red_count=reds,
        regime_yellow_count=yellows,
        indicator_version=INDICATOR_VERSION,
        computed_at=computed_at,
    )
    MarketSnapshotRepository(db).upsert(snap_row)

    MarketPostureStreakRepository(db).record_posture(
        as_of_date=trade_date,
        posture=posture,
        computed_at=computed_at,
    )
    return posture


def _load_price_frame(
    prices: DailyPriceRepository,
    symbol: str,
    today: date,
) -> pd.DataFrame | None:
    """Load 2 years of daily OHLCV from DB → DataFrame for signal calcs.

    Mirrors the helper in ``ingestion/indicators.py`` — duplicated
    (DRY violation acknowledged) rather than cross-imported because:
    (a) making ``indicators`` depend on ``signals`` creates a cycle,
    (b) the shape differs subtly in the future (signal tier compute
    only needs 200 bars; indicators want 2 years for weekly RSI).
    """
    start = (pd.Timestamp(today) - pd.DateOffset(years=2)).date()
    rows = prices.get_range(symbol, start=start, end=today)
    if not rows:
        return None
    records = [
        {
            "date": r.date,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume),
        }
        for r in rows
    ]
    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()

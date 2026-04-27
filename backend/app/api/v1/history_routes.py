"""History endpoints (Phase 5).

* GET /history/market-posture    — last N days of MarketSnapshot rows
  for the dashboard's mini sparkline. ``days`` capped at 365.
* GET /history/signal-accuracy   — per-symbol back-test accuracy:
  for each historical TickerSnapshot, did the action's directional
  sign match the N-day forward return? Used on the per-ticker
  TickerDetail page.
* GET /history/decisions         — caller's last N trades joined with
  the Eiswein recommendation on the same trade date. Cosine-similarity
  pattern matching is explicitly out of scope for this phase.

Pattern matching across the broader trade history (cosine similarity
vs historical signals) will land in a later phase.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_daily_price_repository,
    get_db_session,
    get_market_snapshot_repository,
    get_ticker_snapshot_repository,
    get_trade_repository,
    get_watchlist_repository,
)
from app.api.v1.watchlist_routes import validate_symbol_or_raise
from app.db.models import (
    DailyPrice,
    MarketSnapshot,
    TickerSnapshot,
)
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.market_snapshot_repository import MarketSnapshotRepository
from app.db.repositories.ticker_snapshot_repository import TickerSnapshotRepository
from app.db.repositories.trade_repository import TradeRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.security.exceptions import NotFoundError
from app.signals.types import ActionCategory

router = APIRouter(tags=["history"])
logger = structlog.get_logger("eiswein.api.history")

HorizonLiteral = Literal[5, 20, 60, 120]
_VALID_HORIZONS: frozenset[int] = frozenset({5, 20, 60, 120})

# SPY is the canonical "buy-and-hold" baseline — same proxy used elsewhere
# (relative-strength, regime indicators). The accuracy endpoint compares
# the user's signal hit rate against the same-period SPY drift so a
# bull-market tailwind doesn't masquerade as system skill.
_BASELINE_SYMBOL = "SPY"

# Actions that express a directional view the accuracy score can test.
# HOLD/WATCH are explicitly excluded — they're "no call" outcomes that
# shouldn't count against or for the system. REDUCE/EXIT vote "down".
_BUY_ACTIONS: frozenset[ActionCategory] = frozenset({ActionCategory.STRONG_BUY, ActionCategory.BUY})
_SELL_ACTIONS: frozenset[ActionCategory] = frozenset({ActionCategory.REDUCE, ActionCategory.EXIT})


# --- /history/market-posture ---------------------------------------------


class PostureHistoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    posture: str
    regime_green_count: int
    regime_red_count: int
    regime_yellow_count: int


class PostureHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[PostureHistoryItem]
    total: int
    has_more: bool = False


@router.get(
    "/history/market-posture",
    response_model=PostureHistoryResponse,
    summary="Recent market-posture timeline",
)
def market_posture_history(
    days: int = Query(default=90, ge=1, le=365),
    _user_id: int = Depends(current_user_id),
    repo: MarketSnapshotRepository = Depends(get_market_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> PostureHistoryResponse:
    # There's no repo method for a bounded range; use a local query so
    # we don't grow the repository surface for a read-only view.
    latest = repo.get_latest()
    if latest is None:
        return PostureHistoryResponse(data=[], total=0, has_more=False)
    cutoff = latest.date - timedelta(days=days)
    stmt = (
        select(MarketSnapshot)
        .where(MarketSnapshot.date >= cutoff)
        .order_by(MarketSnapshot.date.asc())
    )
    rows = session.execute(stmt).scalars().all()
    data = [
        PostureHistoryItem(
            date=row.date,
            posture=row.posture,
            regime_green_count=row.regime_green_count,
            regime_red_count=row.regime_red_count,
            regime_yellow_count=row.regime_yellow_count,
        )
        for row in rows
    ]
    return PostureHistoryResponse(data=data, total=len(data), has_more=False)


# --- /history/signal-accuracy --------------------------------------------


class AccuracyBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    correct: int
    accuracy_pct: float


class SignalAccuracyBaseline(BaseModel):
    """Same-period SPY drift baseline.

    For each date in the user's signal sample we ask "did SPY itself rise
    over the same horizon?". The resulting "always-buy" accuracy gives
    the user a market-tailwind benchmark — a system that beats SPY drift
    is genuinely directional; one that trails it is just noise around
    market beta.
    """

    model_config = ConfigDict(frozen=True)

    total: int
    spy_up_count: int
    spy_up_pct: float


class SignalAccuracyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    horizon: HorizonLiteral
    total_signals: int
    correct: int
    accuracy_pct: float
    by_action: dict[str, AccuracyBucket]
    baseline: SignalAccuracyBaseline


@dataclass(frozen=True)
class _AccuracyEval:
    total: int
    correct: int

    @property
    def pct(self) -> float:
        return round(100.0 * self.correct / self.total, 2) if self.total else 0.0


def _eval_accuracy(
    *,
    snapshots: list[TickerSnapshot],
    price_by_date: dict[date, Decimal],
    horizon_days: int,
) -> tuple[_AccuracyEval, dict[str, _AccuracyEval]]:
    """Evaluate accuracy of directional calls against forward returns.

    A buy-side action is "correct" if the price on
    ``snapshot.date + horizon_days`` (or the nearest later trading
    day in our data) is strictly greater than the close on
    ``snapshot.date``. Sell-side is the opposite. Calls without enough
    forward data are skipped entirely — they don't count as correct
    OR incorrect.
    """
    sorted_dates = sorted(price_by_date.keys())
    total = 0
    correct = 0
    per_action: dict[str, tuple[int, int]] = {}

    for snapshot in snapshots:
        action_str = snapshot.action
        try:
            action = ActionCategory(action_str)
        except ValueError:
            continue
        if action not in _BUY_ACTIONS and action not in _SELL_ACTIONS:
            continue  # HOLD / WATCH don't express a directional view

        start_price = price_by_date.get(snapshot.date)
        if start_price is None:
            continue
        target_date = snapshot.date + timedelta(days=horizon_days)
        forward_date = _first_on_or_after(sorted_dates, target_date)
        if forward_date is None:
            continue
        forward_price = price_by_date[forward_date]

        went_up = forward_price > start_price
        call_was_up = action in _BUY_ACTIONS
        is_correct = went_up == call_was_up

        total += 1
        if is_correct:
            correct += 1
        t_count, c_count = per_action.get(action_str, (0, 0))
        per_action[action_str] = (
            t_count + 1,
            c_count + (1 if is_correct else 0),
        )

    overall = _AccuracyEval(total=total, correct=correct)
    buckets = {name: _AccuracyEval(total=t, correct=c) for name, (t, c) in per_action.items()}
    return overall, buckets


def _first_on_or_after(sorted_dates: list[date], target: date) -> date | None:
    # Linear scan — trade-history + 1y of forward data stays small
    # enough (≤ ~250 per symbol) that the simpler code beats bisect
    # for readability.
    for d in sorted_dates:
        if d >= target:
            return d
    return None


def _eval_baseline(
    *,
    signal_dates: list[date],
    spy_price_by_date: dict[date, Decimal],
    horizon_days: int,
) -> tuple[int, int]:
    """SPY drift baseline over the same dates the user's signals fired.

    Returns ``(total, up_count)`` where ``total`` is the number of dates
    we could resolve a forward price for, and ``up_count`` is how many
    of those saw SPY rise. Same skip rule as :func:`_eval_accuracy` —
    dates without enough forward data are dropped, not penalised.
    """
    sorted_spy_dates = sorted(spy_price_by_date.keys())
    total = 0
    up = 0
    for d in signal_dates:
        start_price = spy_price_by_date.get(d)
        if start_price is None:
            continue
        target_date = d + timedelta(days=horizon_days)
        forward_date = _first_on_or_after(sorted_spy_dates, target_date)
        if forward_date is None:
            continue
        if spy_price_by_date[forward_date] > start_price:
            up += 1
        total += 1
    return total, up


@router.get(
    "/history/signal-accuracy",
    response_model=SignalAccuracyResponse,
    summary="Back-tested directional accuracy of stored signals",
)
def signal_accuracy(
    symbol: str = Query(..., min_length=1, max_length=10),
    # Upper bound matches the longest entry in `_VALID_HORIZONS` (120).
    # The whitelist below still enforces the discrete set, but Query
    # bounds run first — leaving `le=60` here would 422-out the 120
    # selection before our enum check could reply with the friendlier
    # "invalid_horizon" body.
    horizon: int = Query(default=20, ge=1, le=120),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> SignalAccuracyResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})
    # Enum-check here rather than on the Query signature: FastAPI's
    # Literal[int] parser doesn't coerce string "5" to 5 and returns a
    # confusing 422. This keeps the whitelist clear in the error body.
    if horizon not in _VALID_HORIZONS:
        from app.security.exceptions import ValidationError as EisweinValidationError

        raise EisweinValidationError(
            details={"reason": "invalid_horizon", "allowed": sorted(_VALID_HORIZONS)}
        )
    horizon_literal = cast(HorizonLiteral, horizon)

    all_snapshots = list(snapshots.list_for_symbol(validated))
    if not all_snapshots:
        return SignalAccuracyResponse(
            symbol=validated,
            horizon=horizon_literal,
            total_signals=0,
            correct=0,
            accuracy_pct=0.0,
            by_action={},
            baseline=SignalAccuracyBaseline(total=0, spy_up_count=0, spy_up_pct=0.0),
        )

    # Load all DailyPrice rows for the symbol in one shot so lookups
    # are O(1) per snapshot. Query directly (repo only exposes range +
    # latest + count) — we want the whole time-series.
    rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == validated)
        .order_by(DailyPrice.date.asc())
    ).all()
    price_by_date = {r.date: Decimal(str(r.close)) for r in rows}

    overall, buckets = _eval_accuracy(
        snapshots=all_snapshots,
        price_by_date=price_by_date,
        horizon_days=int(horizon),
    )

    # Same-period SPY drift baseline. We pull SPY closes once and reuse
    # the same forward-date lookup the accuracy eval uses, so the
    # baseline draws from the exact same date set the system was
    # judged on (avoids "system tested on 2024 but baseline on 2026"
    # apples-to-oranges comparisons).
    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _BASELINE_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_price_by_date = {r.date: Decimal(str(r.close)) for r in spy_rows}
    signal_dates = [s.date for s in all_snapshots]
    baseline_total, baseline_up = _eval_baseline(
        signal_dates=signal_dates,
        spy_price_by_date=spy_price_by_date,
        horizon_days=int(horizon),
    )
    baseline_pct = round(100.0 * baseline_up / baseline_total, 2) if baseline_total else 0.0

    return SignalAccuracyResponse(
        symbol=validated,
        horizon=horizon_literal,
        total_signals=overall.total,
        correct=overall.correct,
        accuracy_pct=overall.pct,
        by_action={
            k: AccuracyBucket(total=v.total, correct=v.correct, accuracy_pct=v.pct)
            for k, v in buckets.items()
        },
        baseline=SignalAccuracyBaseline(
            total=baseline_total,
            spy_up_count=baseline_up,
            spy_up_pct=baseline_pct,
        ),
    )


# --- /history/decisions --------------------------------------------------


class DecisionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_id: int
    trade_date: datetime
    symbol: str
    side: str
    shares: str
    price: str
    eiswein_action: str | None
    matched_recommendation: bool | None


class DecisionHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[DecisionItem]
    total: int
    has_more: bool = False


def _matches(side: str, action: ActionCategory) -> bool:
    if side == "buy":
        return action in _BUY_ACTIONS or action == ActionCategory.HOLD
    if side == "sell":
        return action in _SELL_ACTIONS
    return False


@router.get(
    "/history/decisions",
    response_model=DecisionHistoryResponse,
    summary="Recent trades aligned with the day's Eiswein recommendation",
)
def decisions_history(
    limit: int = Query(default=30, ge=1, le=200),
    user_id: int = Depends(current_user_id),
    trades: TradeRepository = Depends(get_trade_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
) -> DecisionHistoryResponse:
    rows = trades.list_for_user(user_id=user_id, limit=limit)
    items: list[DecisionItem] = []
    # Group snapshot lookups by symbol to reduce redundant round-trips
    # when the same symbol appears many times.
    snapshot_cache: dict[tuple[str, date], TickerSnapshot | None] = {}
    for trade in rows:
        trade_day = trade.executed_at.astimezone(UTC).date()
        key = (trade.symbol, trade_day)
        if key not in snapshot_cache:
            snapshot_cache[key] = snapshots.get_on_or_before(
                symbol=trade.symbol, on_or_before=trade_day
            )
        snapshot = snapshot_cache[key]
        action_str: str | None = None
        matched: bool | None = None
        if snapshot is not None:
            action_str = snapshot.action
            try:
                action = ActionCategory(snapshot.action)
                matched = _matches(trade.side, action)
            except ValueError:
                matched = None
        items.append(
            DecisionItem(
                trade_id=trade.id,
                trade_date=trade.executed_at,
                symbol=trade.symbol,
                side=trade.side,
                shares=str(Decimal(str(trade.shares)).quantize(Decimal("0.000001"))),
                price=str(Decimal(str(trade.price)).quantize(Decimal("0.000001"))),
                eiswein_action=action_str,
                matched_recommendation=matched,
            )
        )
    return DecisionHistoryResponse(data=items, total=len(items), has_more=False)

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
    DailySignal,
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

# Regime indicator names voted into the posture. Mirror of
# `app/signals/market_posture.REGIME_INDICATOR_NAMES`. Kept local
# (not imported) so this read endpoint doesn't depend on the signal
# composition layer at module import time.
_REGIME_INDICATOR_NAMES: tuple[str, ...] = (
    "spx_ma",
    "ad_day",
    "vix",
    "yield_spread",
)
_SPX_PROXY_SYMBOL = "SPY"


class PostureHistoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    posture: str
    regime_green_count: int
    regime_red_count: int
    regime_yellow_count: int
    # New: SPY close + per-indicator vote so the frontend can paint the
    # price line + posture-tinted background and surface a 4-indicator
    # breakdown on hover. Both are optional — older snapshots predating
    # the indicator backfill may have neither.
    spy_close: float | None = None
    # SPX 50/200-day SMA values (proxied via SPY closes), echoed per day
    # so the chart can overlay them as auxiliary trend reference lines.
    # Two of the four regime indicators (SPX 多頭) come from these MAs,
    # so plotting them turns the abstract "spx_ma=red" tag into a
    # visible cross. Null when the trailing window doesn't have enough
    # data (typically the leftmost ~200 days of available SPY history).
    spy_ma50: float | None = None
    spy_ma200: float | None = None
    regime_signals: dict[str, str] = {}


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

    # Pull SPY closes + the 4 regime indicator votes in one shot each so
    # we can attach them per-day without N+1 queries. The regime
    # indicators are persisted as DailySignal rows with symbol='SPY'
    # (see ingestion/indicators._SPX_SYMBOL).
    #
    # We deliberately don't filter SPY by `date >= cutoff` here: the
    # MA50 / MA200 overlay needs ~200 prior calendar days of context to
    # warm up the rolling window, otherwise MA200 would be null for the
    # entire visible range whenever the user picks ≤ 200D. Pulling the
    # full SPY series is one extra query of a few KB; cheap.
    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _SPX_PROXY_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_close_by_date: dict[date, float] = {r.date: float(r.close) for r in spy_rows}
    spy_ma50_by_date, spy_ma200_by_date = _spy_moving_averages(spy_rows)

    regime_rows = session.execute(
        select(DailySignal.date, DailySignal.indicator_name, DailySignal.signal)
        .where(DailySignal.symbol == _SPX_PROXY_SYMBOL)
        .where(DailySignal.indicator_name.in_(_REGIME_INDICATOR_NAMES))
        .where(DailySignal.date >= cutoff)
    ).all()
    regime_by_date: dict[date, dict[str, str]] = {}
    for r in regime_rows:
        regime_by_date.setdefault(r.date, {})[r.indicator_name] = r.signal

    data = [
        PostureHistoryItem(
            date=row.date,
            posture=row.posture,
            regime_green_count=row.regime_green_count,
            regime_red_count=row.regime_red_count,
            regime_yellow_count=row.regime_yellow_count,
            spy_close=spy_close_by_date.get(row.date),
            spy_ma50=spy_ma50_by_date.get(row.date),
            spy_ma200=spy_ma200_by_date.get(row.date),
            regime_signals=regime_by_date.get(row.date, {}),
        )
        for row in rows
    ]
    return PostureHistoryResponse(data=data, total=len(data), has_more=False)


def _spy_moving_averages(
    spy_rows: list,  # list of Row(date, close), date-ascending
) -> tuple[dict[date, float], dict[date, float]]:
    """Compute SMA50 and SMA200 per date from a date-ascending close list.

    Hand-rolled deque-style rolling sum so we don't have to pull pandas
    in to a read endpoint that otherwise stays in plain SQL/dict land.
    Days where the window isn't yet full are simply absent from the
    output dict — callers use ``.get()`` to default to ``None``.
    """
    ma50: dict[date, float] = {}
    ma200: dict[date, float] = {}
    if not spy_rows:
        return ma50, ma200
    closes: list[float] = []
    sum50 = 0.0
    sum200 = 0.0
    for r in spy_rows:
        c = float(r.close)
        closes.append(c)
        sum50 += c
        sum200 += c
        if len(closes) > 50:
            sum50 -= closes[-51]
        if len(closes) > 200:
            sum200 -= closes[-201]
        if len(closes) >= 50:
            ma50[r.date] = sum50 / 50.0
        if len(closes) >= 200:
            ma200[r.date] = sum200 / 200.0
    return ma50, ma200


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
    # NOTE: full-spectrum action distribution lives client-side now, derived
    # from the same /ticker-signals data the chart consumes — that way the
    # numbers always match the timeline window the user is looking at.


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
    # Window length in calendar days. The accuracy is computed only
    # over snapshots within `(today - days, today]` so the chart, the
    # distribution and the accuracy table all describe the same
    # period — a window-of-365D + horizon-of-120D combo will naturally
    # leave only ~245 gradeable days, surfaced via the existing
    # sample-size warning. ``None`` falls back to whole-history
    # behaviour for legacy callers.
    days: int | None = Query(default=None, ge=30, le=730),
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
    # Apply the optional window. The newest snapshot date defines the
    # cutoff so the window slides with the data, not with the request
    # clock — matches what /ticker-signals does for the chart.
    if days is not None and all_snapshots:
        latest = max(s.date for s in all_snapshots)
        cutoff = latest - timedelta(days=days)
        all_snapshots = [s for s in all_snapshots if s.date >= cutoff]
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


# --- /history/posture-accuracy -------------------------------------------

# Posture → directional expectation. Symmetric to the per-ticker
# accuracy logic: 進攻 expects SPX up, 防守 expects down, 正常 has no
# directional view (excluded from the score).
_POSTURE_BUY: frozenset[str] = frozenset({"offensive"})
_POSTURE_SELL: frozenset[str] = frozenset({"defensive"})


class PostureAccuracyBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    correct: int
    accuracy_pct: float


class PostureAccuracyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: HorizonLiteral
    days: int | None
    total_signals: int
    correct: int
    accuracy_pct: float
    by_posture: dict[str, PostureAccuracyBucket]
    # Same SPY-drift baseline used by /signal-accuracy. Lets the
    # frontend reuse the same "system beats baseline" tinting logic.
    baseline: SignalAccuracyBaseline


@router.get(
    "/history/posture-accuracy",
    response_model=PostureAccuracyResponse,
    summary="Forward-test market posture against SPY drift",
)
def posture_accuracy(
    horizon: int = Query(default=20, ge=1, le=120),
    days: int | None = Query(default=None, ge=30, le=730),
    _user_id: int = Depends(current_user_id),
    session: Session = Depends(get_db_session),
) -> PostureAccuracyResponse:
    if horizon not in _VALID_HORIZONS:
        from app.security.exceptions import ValidationError as EisweinValidationError

        raise EisweinValidationError(
            details={"reason": "invalid_horizon", "allowed": sorted(_VALID_HORIZONS)}
        )
    horizon_literal = cast(HorizonLiteral, horizon)

    snap_rows = session.execute(
        select(MarketSnapshot.date, MarketSnapshot.posture).order_by(MarketSnapshot.date.asc())
    ).all()
    if not snap_rows:
        empty_baseline = SignalAccuracyBaseline(total=0, spy_up_count=0, spy_up_pct=0.0)
        return PostureAccuracyResponse(
            horizon=horizon_literal,
            days=days,
            total_signals=0,
            correct=0,
            accuracy_pct=0.0,
            by_posture={},
            baseline=empty_baseline,
        )

    if days is not None:
        latest = snap_rows[-1].date
        cutoff = latest - timedelta(days=days)
        snap_rows = [r for r in snap_rows if r.date >= cutoff]

    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _SPX_PROXY_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_price_by_date: dict[date, Decimal] = {r.date: Decimal(str(r.close)) for r in spy_rows}

    sorted_spy_dates = sorted(spy_price_by_date.keys())
    total = 0
    correct = 0
    per_posture: dict[str, tuple[int, int]] = {}

    for snap in snap_rows:
        posture = snap.posture
        # Symmetric to ActionCategory: only directional postures count.
        if posture not in _POSTURE_BUY and posture not in _POSTURE_SELL:
            continue
        start_price = spy_price_by_date.get(snap.date)
        if start_price is None:
            continue
        target_date = snap.date + timedelta(days=horizon)
        forward_date = _first_on_or_after(sorted_spy_dates, target_date)
        if forward_date is None:
            continue
        forward_price = spy_price_by_date[forward_date]

        went_up = forward_price > start_price
        call_was_up = posture in _POSTURE_BUY
        is_correct = went_up == call_was_up

        total += 1
        if is_correct:
            correct += 1
        t_count, c_count = per_posture.get(posture, (0, 0))
        per_posture[posture] = (t_count + 1, c_count + (1 if is_correct else 0))

    # Same-period SPY drift baseline — uses the same date list as the
    # accuracy itself so the comparison is window-aligned.
    baseline_dates = [r.date for r in snap_rows]
    baseline_total, baseline_up = _eval_baseline(
        signal_dates=baseline_dates,
        spy_price_by_date=spy_price_by_date,
        horizon_days=int(horizon),
    )
    baseline_pct = round(100.0 * baseline_up / baseline_total, 2) if baseline_total else 0.0

    overall_pct = round(100.0 * correct / total, 2) if total else 0.0
    return PostureAccuracyResponse(
        horizon=horizon_literal,
        days=days,
        total_signals=total,
        correct=correct,
        accuracy_pct=overall_pct,
        by_posture={
            k: PostureAccuracyBucket(
                total=t,
                correct=c,
                accuracy_pct=round(100.0 * c / t, 2) if t else 0.0,
            )
            for k, (t, c) in per_posture.items()
        },
        baseline=SignalAccuracyBaseline(
            total=baseline_total,
            spy_up_count=baseline_up,
            spy_up_pct=baseline_pct,
        ),
    )


# --- /history/ticker-signals ---------------------------------------------


class TickerSignalPoint(BaseModel):
    """One day in the per-stock signal-vs-price overlay.

    Carries the close (for the price line) plus the stored action (for
    a marker in the chart). Forward-evaluation horizons are computed
    client-side from the same row sequence — keeping the wire payload
    minimal and the math reproducible alongside the existing
    /signal-accuracy endpoint.
    """

    model_config = ConfigDict(frozen=True)

    date: date
    action: str
    close: float


class TickerSignalsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    data: list[TickerSignalPoint]


@router.get(
    "/history/ticker-signals",
    response_model=TickerSignalsResponse,
    summary="Per-day action + close for the signal-overlay chart",
)
def ticker_signals_history(
    symbol: str = Query(..., min_length=1, max_length=10),
    days: int = Query(default=180, ge=30, le=730),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> TickerSignalsResponse:
    """Return per-day {date, action, close} for the chosen symbol.

    Joined in Python rather than a SQL JOIN so we don't have to pull
    `daily_price` into the snapshot repository — both tables already
    expose efficient single-table accessors. The trailing window is
    bounded by the latest snapshot date so the chart aligns with the
    market calendar (no empty rightmost days).
    """
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    all_snapshots = list(snapshots.list_for_symbol(validated))
    if not all_snapshots:
        return TickerSignalsResponse(symbol=validated, data=[])

    latest = max(s.date for s in all_snapshots)
    cutoff = latest - timedelta(days=days)
    snapshots_in_window = [s for s in all_snapshots if s.date >= cutoff]
    if not snapshots_in_window:
        return TickerSignalsResponse(symbol=validated, data=[])

    # Pull close prices for the window in one shot. The SPY accuracy
    # endpoint reads the same way; if this turns into a hot path we can
    # promote the helper to the repository.
    rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == validated)
        .where(DailyPrice.date >= cutoff)
        .order_by(DailyPrice.date.asc())
    ).all()
    close_by_date = {r.date: float(r.close) for r in rows}

    points: list[TickerSignalPoint] = []
    for snap in sorted(snapshots_in_window, key=lambda s: s.date):
        close = close_by_date.get(snap.date)
        if close is None:
            # Skip days where we don't have a stored price (e.g. a
            # holiday that produced a snapshot via fallback). Better to
            # drop the point than to plot a misaligned price.
            continue
        points.append(
            TickerSignalPoint(date=snap.date, action=snap.action, close=close)
        )

    return TickerSignalsResponse(symbol=validated, data=points)


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

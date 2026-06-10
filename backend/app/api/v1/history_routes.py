"""History endpoints (Phase 5).

* GET /history/market-posture    — last N days of MarketSnapshot rows
  for the dashboard's mini sparkline. ``days`` capped at 365.
* GET /history/signal-accuracy   — per-symbol back-test accuracy:
  for each historical TickerSnapshot, did the action's directional
  sign match the N-day forward return? Used on the per-ticker
  TickerDetail page.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

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

# Actions that express a 3-class directional view the accuracy score can test:
# BUY-side expects price to rise, SELL-side expects price to fall, FLAT-side
# (HOLD/WATCH) expects price to stay inside ±_FLAT_TOLERANCE_PCT — that's
# also a "directional call", just for "no big move". Counting flat hits as
# evaluable signals roughly 6x the gradeable sample (from ~16% to ~100%
# of stored snapshots in dev DB) without compromising honesty.
_BUY_ACTIONS: frozenset[ActionCategory] = frozenset({ActionCategory.STRONG_BUY, ActionCategory.BUY})
_SELL_ACTIONS: frozenset[ActionCategory] = frozenset({ActionCategory.REDUCE, ActionCategory.EXIT})
_FLAT_ACTIONS: frozenset[ActionCategory] = frozenset({ActionCategory.HOLD, ActionCategory.WATCH})

# ±2 % band over the chosen horizon counts as "flat" for grading. 2 %
# is wider than typical 20-day noise on SPX-style names; for high-beta
# small caps it may classify too aggressively, but symmetric error is
# preferable to the binary up/down classification that came before.
_FLAT_TOLERANCE_PCT = 2.0


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
    spy_rows: Sequence[Any],  # rows shaped (date, close), date-ascending
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
    # Phase 6 (2026-06) magnitude-weighted accuracy. ``avg_return_pct`` is
    # the average forward % return earned if you followed every signal in
    # this bucket: long on BUY, short on SELL, cash (0%) on HOLD/WATCH.
    # ``baseline_avg_return_pct`` is the matched SPY return over the same
    # dates (long for BUY rows, short for SELL rows, 0 for FLAT rows).
    # ``delta_vs_baseline`` is the alpha vs that baseline.
    avg_return_pct: float = 0.0
    baseline_avg_return_pct: float = 0.0
    delta_vs_baseline: float = 0.0


class SignalAccuracyBaseline(BaseModel):
    """Same-period SPY drift baseline, 3-class.

    For each date in the user's signal sample we tag SPY's own forward
    move as up / down / flat (same ±2 % tolerance as the user's grading).
    The resulting distribution gives the frontend three matched
    benchmarks: BUY actions vs ``spy_up_pct``, SELL vs ``spy_down_pct``,
    HOLD/WATCH vs ``spy_flat_pct``. A system that exceeds the matching
    baseline on any class is genuinely directional in that class.
    """

    model_config = ConfigDict(frozen=True)

    total: int
    spy_up_count: int
    spy_up_pct: float
    # Phase 6 (2026-06): per-class breakdown so HOLD/WATCH/normal
    # signals have a meaningful baseline to compare against.
    spy_down_count: int = 0
    spy_down_pct: float = 0.0
    spy_flat_count: int = 0
    spy_flat_pct: float = 0.0


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
    # Sum of per-signal % returns under the "follow the signal" trade rule
    # (long on BUY, short on SELL, cash on FLAT). Divided by ``total`` to
    # get the per-signal average return. Stored as a sum rather than a
    # running average so per-bucket aggregation stays exact.
    return_sum_pct: float = 0.0
    spy_return_sum_pct: float = 0.0

    @property
    def pct(self) -> float:
        return round(100.0 * self.correct / self.total, 2) if self.total else 0.0

    @property
    def avg_return_pct(self) -> float:
        return round(self.return_sum_pct / self.total, 3) if self.total else 0.0

    @property
    def spy_avg_return_pct(self) -> float:
        return round(self.spy_return_sum_pct / self.total, 3) if self.total else 0.0


_MoveClass = Literal["up", "down", "flat"]


def _signal_return(expected: _MoveClass, start: Decimal, forward: Decimal) -> float:
    """% return earned by trading the implied position.

    BUY (expected="up"): long, P&L = (forward - start) / start
    SELL (expected="down"): short, P&L = (start - forward) / start
    FLAT (expected="flat"): cash, P&L = 0
    """
    if expected == "flat" or start <= 0:
        return 0.0
    raw = float((forward - start) / start * 100)
    return raw if expected == "up" else -raw


def _classify_move(start: Decimal, forward: Decimal) -> _MoveClass:
    """3-class direction tagging with a ±``_FLAT_TOLERANCE_PCT`` band.

    Used by both ticker-level accuracy (BUY/SELL/HOLD action grading) and
    market-posture accuracy (offensive/defensive/normal). The tolerance
    band lets HOLD/WATCH and ``normal`` posture actually be gradeable —
    a "no big move" call should hit when the market obliges.
    """
    if start <= 0:
        return "flat"
    pct = float((forward - start) / start * 100)
    if pct > _FLAT_TOLERANCE_PCT:
        return "up"
    if pct < -_FLAT_TOLERANCE_PCT:
        return "down"
    return "flat"


def _expected_move(action: ActionCategory) -> _MoveClass | None:
    """Map an ActionCategory to the move class the action implicitly predicts.

    Returns ``None`` for actions outside the buy/sell/flat sets — currently
    none, but kept future-proof in case a new category lands without
    a directional view.
    """
    if action in _BUY_ACTIONS:
        return "up"
    if action in _SELL_ACTIONS:
        return "down"
    if action in _FLAT_ACTIONS:
        return "flat"
    return None


@dataclass
class _ActionRunning:
    total: int = 0
    correct: int = 0
    return_sum_pct: float = 0.0
    spy_return_sum_pct: float = 0.0


def _eval_accuracy(
    *,
    snapshots: list[TickerSnapshot],
    price_by_date: dict[date, Decimal],
    horizon_days: int,
    spy_price_by_date: dict[date, Decimal] | None = None,
) -> tuple[_AccuracyEval, dict[str, _AccuracyEval]]:
    """Evaluate accuracy + magnitude-weighted returns against forward prices.

    3-class direction grading via :func:`_classify_move`. The same loop
    additionally accumulates the per-signal % return assuming you traded
    the implied position (long on BUY, short on SELL, cash on FLAT), plus
    the matched SPY return over the same dates — so the response carries
    both the hit-rate AND the "what % did you actually earn" reading.

    Calls without enough forward data on EITHER side (stock or SPY when
    a SPY frame is supplied) are skipped — they don't count as correct
    or incorrect, nor toward the return sums.
    """
    sorted_dates = sorted(price_by_date.keys())
    sorted_spy_dates = sorted(spy_price_by_date.keys()) if spy_price_by_date else []
    overall_running = _ActionRunning()
    per_action: dict[str, _ActionRunning] = {}

    for snapshot in snapshots:
        action_str = snapshot.action
        try:
            action = ActionCategory(action_str)
        except ValueError:
            continue
        expected = _expected_move(action)
        if expected is None:
            continue

        start_price = price_by_date.get(snapshot.date)
        if start_price is None:
            continue
        target_date = snapshot.date + timedelta(days=horizon_days)
        forward_date = _first_on_or_after(sorted_dates, target_date)
        if forward_date is None:
            continue
        forward_price = price_by_date[forward_date]
        actual = _classify_move(start_price, forward_price)
        is_correct = actual == expected
        signal_return = _signal_return(expected, start_price, forward_price)

        # Matched SPY return: same direction (long for BUY, short for SELL,
        # 0 for FLAT) so the bucket-level comparison is fair.
        spy_return = 0.0
        if spy_price_by_date is not None:
            spy_start = spy_price_by_date.get(snapshot.date)
            spy_forward_date = _first_on_or_after(sorted_spy_dates, target_date)
            if spy_start is not None and spy_forward_date is not None:
                spy_forward = spy_price_by_date[spy_forward_date]
                spy_return = _signal_return(expected, spy_start, spy_forward)

        overall_running.total += 1
        overall_running.return_sum_pct += signal_return
        overall_running.spy_return_sum_pct += spy_return
        if is_correct:
            overall_running.correct += 1
        bucket = per_action.setdefault(action_str, _ActionRunning())
        bucket.total += 1
        bucket.return_sum_pct += signal_return
        bucket.spy_return_sum_pct += spy_return
        if is_correct:
            bucket.correct += 1

    overall = _AccuracyEval(
        total=overall_running.total,
        correct=overall_running.correct,
        return_sum_pct=overall_running.return_sum_pct,
        spy_return_sum_pct=overall_running.spy_return_sum_pct,
    )
    buckets = {
        name: _AccuracyEval(
            total=r.total,
            correct=r.correct,
            return_sum_pct=r.return_sum_pct,
            spy_return_sum_pct=r.spy_return_sum_pct,
        )
        for name, r in per_action.items()
    }
    return overall, buckets


def _first_on_or_after(sorted_dates: list[date], target: date) -> date | None:
    # Linear scan — trade-history + 1y of forward data stays small
    # enough (≤ ~250 per symbol) that the simpler code beats bisect
    # for readability.
    for d in sorted_dates:
        if d >= target:
            return d
    return None


@dataclass(frozen=True)
class _BaselineCounts:
    total: int
    up: int
    down: int
    flat: int


def _eval_baseline(
    *,
    signal_dates: list[date],
    spy_price_by_date: dict[date, Decimal],
    horizon_days: int,
) -> _BaselineCounts:
    """SPY drift baseline over the same dates the user's signals fired.

    Returns SPY's own up/down/flat distribution (3-class, same ±tolerance
    band as the user's grading) so the frontend can compare each per-action
    bucket against the matching baseline (BUY vs SPY up%, SELL vs SPY
    down%, HOLD/WATCH vs SPY flat%). Same skip rule as :func:`_eval_accuracy`
    — dates without enough forward data are dropped, not penalised.
    """
    sorted_spy_dates = sorted(spy_price_by_date.keys())
    total = 0
    up = 0
    down = 0
    flat = 0
    for d in signal_dates:
        start_price = spy_price_by_date.get(d)
        if start_price is None:
            continue
        target_date = d + timedelta(days=horizon_days)
        forward_date = _first_on_or_after(sorted_spy_dates, target_date)
        if forward_date is None:
            continue
        actual = _classify_move(start_price, spy_price_by_date[forward_date])
        if actual == "up":
            up += 1
        elif actual == "down":
            down += 1
        else:
            flat += 1
        total += 1
    return _BaselineCounts(total=total, up=up, down=down, flat=flat)


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

    overall, buckets = _eval_accuracy(
        snapshots=all_snapshots,
        price_by_date=price_by_date,
        horizon_days=int(horizon),
        spy_price_by_date=spy_price_by_date,
    )

    signal_dates = [s.date for s in all_snapshots]
    baseline = _eval_baseline(
        signal_dates=signal_dates,
        spy_price_by_date=spy_price_by_date,
        horizon_days=int(horizon),
    )
    baseline_payload = _baseline_to_schema(baseline)

    return SignalAccuracyResponse(
        symbol=validated,
        horizon=horizon_literal,
        total_signals=overall.total,
        correct=overall.correct,
        accuracy_pct=overall.pct,
        by_action={
            k: AccuracyBucket(
                total=v.total,
                correct=v.correct,
                accuracy_pct=v.pct,
                avg_return_pct=v.avg_return_pct,
                baseline_avg_return_pct=v.spy_avg_return_pct,
                delta_vs_baseline=round(v.avg_return_pct - v.spy_avg_return_pct, 3),
            )
            for k, v in buckets.items()
        },
        baseline=baseline_payload,
    )


def _baseline_to_schema(b: _BaselineCounts) -> SignalAccuracyBaseline:
    """Convert :class:`_BaselineCounts` to the wire schema with rounded pcts."""
    if b.total == 0:
        return SignalAccuracyBaseline(total=0, spy_up_count=0, spy_up_pct=0.0)
    return SignalAccuracyBaseline(
        total=b.total,
        spy_up_count=b.up,
        spy_up_pct=round(100.0 * b.up / b.total, 2),
        spy_down_count=b.down,
        spy_down_pct=round(100.0 * b.down / b.total, 2),
        spy_flat_count=b.flat,
        spy_flat_pct=round(100.0 * b.flat / b.total, 2),
    )


# --- /history/posture-accuracy -------------------------------------------

# Posture → directional expectation. Symmetric to the per-ticker
# accuracy logic: 進攻 expects SPX up, 防守 expects down, 正常 has no
# directional view (excluded from the score).
_POSTURE_BUY: frozenset[str] = frozenset({"offensive"})
_POSTURE_SELL: frozenset[str] = frozenset({"defensive"})
_POSTURE_FLAT: frozenset[str] = frozenset({"normal"})


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
        if (
            posture not in _POSTURE_BUY
            and posture not in _POSTURE_SELL
            and posture not in _POSTURE_FLAT
        ):
            continue
        start_price = spy_price_by_date.get(snap.date)
        if start_price is None:
            continue
        target_date = snap.date + timedelta(days=horizon)
        forward_date = _first_on_or_after(sorted_spy_dates, target_date)
        if forward_date is None:
            continue
        actual = _classify_move(start_price, spy_price_by_date[forward_date])
        if posture in _POSTURE_BUY:
            expected: _MoveClass = "up"
        elif posture in _POSTURE_SELL:
            expected = "down"
        else:
            expected = "flat"
        is_correct = actual == expected

        total += 1
        if is_correct:
            correct += 1
        t_count, c_count = per_posture.get(posture, (0, 0))
        per_posture[posture] = (t_count + 1, c_count + (1 if is_correct else 0))

    # Same-period SPY drift baseline — uses the same date list as the
    # accuracy itself so the comparison is window-aligned.
    baseline_dates = [r.date for r in snap_rows]
    baseline = _eval_baseline(
        signal_dates=baseline_dates,
        spy_price_by_date=spy_price_by_date,
        horizon_days=int(horizon),
    )

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
        baseline=_baseline_to_schema(baseline),
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
        points.append(TickerSignalPoint(date=snap.date, action=snap.action, close=close))

    return TickerSignalsResponse(symbol=validated, data=points)


# --- /history/symbol-accuracy-ranking ------------------------------------


class SymbolAccuracyEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    total_signals: int
    correct: int
    accuracy_pct: float


class SymbolAccuracyRankingResponse(BaseModel):
    """Per-watchlist-symbol hit-rate ranking for the history page card.

    Aggregates the same accuracy logic used by /history/signal-accuracy
    across every symbol on the caller's watchlist, sorted descending by
    accuracy. Window matches the history page's range selector
    (30D / 90D / 365D); horizon is fixed at 20-day to keep the ranking
    comparable across tickers without forcing the operator into a
    second selector. Symbols with zero gradeable snapshots in the
    window are still included (accuracy_pct=0, total_signals=0) so the
    UI can hint "needs more data" rather than silently omitting them.
    """

    model_config = ConfigDict(frozen=True)

    horizon: HorizonLiteral
    days: int
    data: list[SymbolAccuracyEntry]
    baseline: SignalAccuracyBaseline


@router.get(
    "/history/symbol-accuracy-ranking",
    response_model=SymbolAccuracyRankingResponse,
    summary="Per-watchlist-symbol hit-rate ranking",
)
def symbol_accuracy_ranking(
    days: int = Query(default=90, ge=30, le=730),
    horizon: int = Query(default=20, ge=1, le=120),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> SymbolAccuracyRankingResponse:
    if horizon not in _VALID_HORIZONS:
        from app.security.exceptions import ValidationError as EisweinValidationError

        raise EisweinValidationError(
            details={"reason": "invalid_horizon", "allowed": sorted(_VALID_HORIZONS)}
        )
    horizon_literal = cast(HorizonLiteral, horizon)

    rows = watchlist.list_for_user(user_id=user_id)
    symbols = sorted({row.symbol for row in rows})

    # Load SPY closes once and reuse for every symbol's baseline + the
    # response-level baseline aggregate.
    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _BASELINE_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_price_by_date = {r.date: Decimal(str(r.close)) for r in spy_rows}

    entries: list[SymbolAccuracyEntry] = []
    aggregate = _BaselineCounts(total=0, up=0, down=0, flat=0)

    for sym in symbols:
        all_snapshots = list(snapshots.list_for_symbol(sym))
        if all_snapshots:
            latest = max(s.date for s in all_snapshots)
            cutoff = latest - timedelta(days=days)
            all_snapshots = [s for s in all_snapshots if s.date >= cutoff]
        if not all_snapshots:
            entries.append(
                SymbolAccuracyEntry(symbol=sym, total_signals=0, correct=0, accuracy_pct=0.0)
            )
            continue

        price_rows = session.execute(
            select(DailyPrice.date, DailyPrice.close)
            .where(DailyPrice.symbol == sym)
            .order_by(DailyPrice.date.asc())
        ).all()
        price_by_date = {r.date: Decimal(str(r.close)) for r in price_rows}

        overall, _ = _eval_accuracy(
            snapshots=all_snapshots,
            price_by_date=price_by_date,
            horizon_days=int(horizon),
        )
        entries.append(
            SymbolAccuracyEntry(
                symbol=sym,
                total_signals=overall.total,
                correct=overall.correct,
                accuracy_pct=overall.pct,
            )
        )

        # Same-period SPY drift baseline contribution.
        b = _eval_baseline(
            signal_dates=[s.date for s in all_snapshots],
            spy_price_by_date=spy_price_by_date,
            horizon_days=int(horizon),
        )
        aggregate = _BaselineCounts(
            total=aggregate.total + b.total,
            up=aggregate.up + b.up,
            down=aggregate.down + b.down,
            flat=aggregate.flat + b.flat,
        )

    entries.sort(key=lambda e: (-e.accuracy_pct, -e.total_signals, e.symbol))

    return SymbolAccuracyRankingResponse(
        horizon=horizon_literal,
        days=days,
        data=entries,
        baseline=_baseline_to_schema(aggregate),
    )


# --- /history/event-study ------------------------------------------------

# Event study horizon points. 1 / 5 / 20 / 60 trading days mirror the
# academic convention (t+1 = next bar, t+5 ~ one week, t+20 ~ one month,
# t+60 ~ one quarter). Calendar days vs trading days: we use calendar
# offsets but resolve forward via ``_first_on_or_after`` so weekends
# slip to the next trading day — same as the accuracy code.
_EVENT_STUDY_HORIZONS: tuple[int, ...] = (1, 5, 20, 60)

# Actions to bucket. Excludes strong_buy/exit because they're rare
# (typically <30 events even on 2-year DBs); reduce captures the
# sell-side signal universe. The bucket label maps to the snapshot
# action string verbatim — the frontend re-labels into 中文 via the
# same ACTION_LABEL it uses for the per-action accuracy table.
_EVENT_STUDY_BUCKETS: tuple[str, ...] = ("buy", "reduce", "hold", "watch")


class EventStudyHorizonStat(BaseModel):
    """Per-horizon t-test on the abnormal-return distribution."""

    model_config = ConfigDict(frozen=True)

    horizon_days: int
    n_events: int
    avg_ar_pct: float  # mean abnormal return % (stock return - SPY return)
    stdev_pct: float
    t_stat: float
    # 2-sided p-value under the standard-normal approximation. For
    # n_events ≥ 30 this is close enough to the t-distribution; for
    # smaller N the frontend renders "N<30 不下結論" and ignores p.
    p_value: float


class EventStudyBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    n_events_total: int
    horizons: list[EventStudyHorizonStat]


class EventStudyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    days: int | None
    by_action: dict[str, EventStudyBucket]


def _normal_two_sided_p(t: float) -> float:
    """2-sided p-value under the standard-normal distribution.

    Avoids importing scipy for a single use. NormalDist is in stdlib
    since 3.8. The tails-approximation breaks down beyond |t| ≈ 8 but
    the result is already 0 to 16 dp by then.
    """
    from statistics import NormalDist

    return round(2.0 * (1.0 - NormalDist().cdf(abs(t))), 6)


def _compute_event_study(
    *,
    snapshots: list[TickerSnapshot],
    price_by_date: dict[date, Decimal],
    spy_price_by_date: dict[date, Decimal],
) -> dict[str, EventStudyBucket]:
    """Build the per-action x per-horizon event-study table.

    For each event at date D and each horizon h:
        stock_return = (close[D+h] - close[D]) / close[D]
        spy_return   = (SPY[D+h]    - SPY[D])   / SPY[D]
        abnormal_return = stock_return - spy_return

    The bucket aggregates the ARs and runs a 1-sample t-test against
    H0: AR = 0. Statistically significant alpha → the indicator
    captured a directional move beyond market drift.
    """
    from statistics import mean, stdev

    sorted_stock_dates = sorted(price_by_date.keys())
    sorted_spy_dates = sorted(spy_price_by_date.keys())

    # Bucket → horizon → list of AR observations.
    ars: dict[str, dict[int, list[float]]] = {
        b: {h: [] for h in _EVENT_STUDY_HORIZONS} for b in _EVENT_STUDY_BUCKETS
    }
    bucket_totals: dict[str, int] = dict.fromkeys(_EVENT_STUDY_BUCKETS, 0)

    for snap in snapshots:
        action_str = snap.action
        if action_str not in ars:
            continue
        bucket_totals[action_str] += 1
        start_stock = price_by_date.get(snap.date)
        start_spy = spy_price_by_date.get(snap.date)
        if start_stock is None or start_spy is None or start_stock <= 0 or start_spy <= 0:
            continue
        for h in _EVENT_STUDY_HORIZONS:
            target = snap.date + timedelta(days=h)
            stock_fwd_date = _first_on_or_after(sorted_stock_dates, target)
            spy_fwd_date = _first_on_or_after(sorted_spy_dates, target)
            if stock_fwd_date is None or spy_fwd_date is None:
                continue
            stock_ret = float((price_by_date[stock_fwd_date] - start_stock) / start_stock)
            spy_ret = float((spy_price_by_date[spy_fwd_date] - start_spy) / start_spy)
            ars[action_str][h].append(stock_ret - spy_ret)

    out: dict[str, EventStudyBucket] = {}
    for action, by_h in ars.items():
        horizons: list[EventStudyHorizonStat] = []
        for h in _EVENT_STUDY_HORIZONS:
            sample = by_h[h]
            n = len(sample)
            if n == 0:
                horizons.append(
                    EventStudyHorizonStat(
                        horizon_days=h,
                        n_events=0,
                        avg_ar_pct=0.0,
                        stdev_pct=0.0,
                        t_stat=0.0,
                        p_value=1.0,
                    )
                )
                continue
            m = mean(sample)
            sd = stdev(sample) if n > 1 else 0.0
            se = sd / (n**0.5) if sd > 0 else 0.0
            t = (m / se) if se > 0 else 0.0
            horizons.append(
                EventStudyHorizonStat(
                    horizon_days=h,
                    n_events=n,
                    avg_ar_pct=round(m * 100, 3),
                    stdev_pct=round(sd * 100, 3),
                    t_stat=round(t, 3),
                    p_value=_normal_two_sided_p(t),
                )
            )
        out[action] = EventStudyBucket(
            action=action,
            n_events_total=bucket_totals[action],
            horizons=horizons,
        )
    return out


@router.get(
    "/history/event-study",
    response_model=EventStudyResponse,
    summary="Event-study abnormal returns + t-test for each action bucket",
)
def event_study(
    symbol: str = Query(..., min_length=1, max_length=10),
    days: int | None = Query(default=None, ge=30, le=730),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> EventStudyResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    all_snapshots = list(snapshots.list_for_symbol(validated))
    if days is not None and all_snapshots:
        latest = max(s.date for s in all_snapshots)
        cutoff = latest - timedelta(days=days)
        all_snapshots = [s for s in all_snapshots if s.date >= cutoff]

    if not all_snapshots:
        return EventStudyResponse(symbol=validated, days=days, by_action={})

    stock_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == validated)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _BASELINE_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    price_by_date = {r.date: Decimal(str(r.close)) for r in stock_rows}
    spy_price_by_date = {r.date: Decimal(str(r.close)) for r in spy_rows}

    by_action = _compute_event_study(
        snapshots=all_snapshots,
        price_by_date=price_by_date,
        spy_price_by_date=spy_price_by_date,
    )
    return EventStudyResponse(symbol=validated, days=days, by_action=by_action)


# --- /history/pnl-simulation ---------------------------------------------

# Trading rule (v2 — fix HOLD/WATCH semantics from MVP):
# * BUY / STRONG_BUY / HOLD + flat → go long all-in on close.
#   HOLD joins as an entry trigger because the indicator's "持有" literally
#   means "the appropriate state is to be in this position"; the previous
#   "do nothing" interpretation kept the simulator in cash for long stretches
#   (in-market 36-41%) when the indicator was effectively saying "you should
#   be holding this".
# * REDUCE / EXIT + in position → close all on close.
# * WATCH → no-op (maintain current state — flat stays flat, position stays
#   long). "觀望" is explicitly "wait and see, don't change anything".
# End-of-window unwind: any open position closes at the last close.
# No stop loss in the MVP — the snapshot's recommended stop is advisory
# only; the operator usually applies it manually.
_PNL_STARTING_CAPITAL = 10_000.0
_PNL_ENTRY_TRIGGERS: frozenset[ActionCategory] = frozenset(
    {ActionCategory.STRONG_BUY, ActionCategory.BUY, ActionCategory.HOLD}
)
_PNL_SELL_TRIGGERS: frozenset[ActionCategory] = frozenset(
    {ActionCategory.REDUCE, ActionCategory.EXIT}
)
_TRADING_DAYS_PER_YEAR = 252


class PnlTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_date: date
    entry_price: float
    entry_action: str
    exit_date: date
    exit_price: float
    exit_reason: str  # 'signal_exit' | 'end_of_window'
    qty: float
    pnl_pct: float
    pnl_abs: float
    holding_days: int


class PnlSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    starting_capital: float
    final_value: float
    total_return_pct: float
    spy_total_return_pct: float
    spy_alpha_pct: float  # total_return - spy_total_return
    # v2: stock buy-and-hold baseline. The "fairer" comparison for a
    # per-symbol strategy — answers "should I follow signals or just
    # buy-and-hold this stock". Positive stock_alpha = signals add value
    # vs lazy buy-and-hold of the same name; negative = signals hurt
    # vs holding through every dip.
    stock_total_return_pct: float
    stock_alpha_pct: float  # total_return - stock_total_return
    n_trades: int
    n_winners: int
    n_losers: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    sharpe_ratio: float  # annualized via sqrt(252)
    max_drawdown_pct: float  # most negative peak-to-trough drawdown
    days_in_market_pct: float  # share of days holding a position


class PnlDailyValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    strategy_value: float  # mark-to-market account value
    spy_baseline_value: float  # $10,000 in SPY bought at start
    stock_baseline_value: float  # $10,000 in this stock bought at start


class PnlSimulationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    days: int | None
    summary: PnlSummary
    trades: list[PnlTrade]
    daily_values: list[PnlDailyValue]


@dataclass
class _OpenPosition:
    entry_date: date
    entry_price: float
    entry_action: str
    qty: float


def _empty_pnl_summary() -> PnlSummary:
    return PnlSummary(
        starting_capital=_PNL_STARTING_CAPITAL,
        final_value=_PNL_STARTING_CAPITAL,
        total_return_pct=0.0,
        spy_total_return_pct=0.0,
        spy_alpha_pct=0.0,
        stock_total_return_pct=0.0,
        stock_alpha_pct=0.0,
        n_trades=0,
        n_winners=0,
        n_losers=0,
        win_rate_pct=0.0,
        avg_win_pct=0.0,
        avg_loss_pct=0.0,
        sharpe_ratio=0.0,
        max_drawdown_pct=0.0,
        days_in_market_pct=0.0,
    )


def _simulate_pnl(
    *,
    snapshots: list[TickerSnapshot],
    price_by_date: dict[date, Decimal],
    spy_price_by_date: dict[date, Decimal],
) -> tuple[PnlSummary, list[PnlTrade], list[PnlDailyValue]]:
    """Walk the snapshot timeline applying the trading rule day by day.

    Mark-to-market account value is recorded each day for Sharpe + max
    drawdown computation. Returns are computed against the SPY drift
    baseline (lump-sum buy SPY at start, hold to end).
    """
    if not snapshots:
        return _empty_pnl_summary(), [], []

    snapshots_by_date = {s.date: s for s in snapshots}
    snap_dates = sorted(snapshots_by_date.keys())
    start_date = snap_dates[0]
    end_date = snap_dates[-1]

    # Walk every date with a price, filtered to the snapshot window. This
    # carries mark-to-market continuously even on days without a snapshot
    # row (rare but possible if the snapshot writer skipped a day).
    all_dates = sorted(d for d in price_by_date if start_date <= d <= end_date)
    if not all_dates:
        return _empty_pnl_summary(), [], []

    cash = _PNL_STARTING_CAPITAL
    position: _OpenPosition | None = None
    trades: list[PnlTrade] = []
    daily_values: list[PnlDailyValue] = []
    days_in_market = 0

    spy_start = float(spy_price_by_date.get(start_date) or 0)
    stock_start = float(price_by_date[start_date])
    stock_baseline_qty = (
        _PNL_STARTING_CAPITAL / stock_start if stock_start > 0 else 0.0
    )

    for d in all_dates:
        close = float(price_by_date[d])
        snap = snapshots_by_date.get(d)
        if snap is not None:
            try:
                action = ActionCategory(snap.action)
            except ValueError:
                action = None
            if action in _PNL_ENTRY_TRIGGERS and position is None and close > 0:
                qty = cash / close
                position = _OpenPosition(
                    entry_date=d,
                    entry_price=close,
                    entry_action=snap.action,
                    qty=qty,
                )
                cash = 0.0
            elif action in _PNL_SELL_TRIGGERS and position is not None:
                proceeds = position.qty * close
                pnl_abs = proceeds - position.qty * position.entry_price
                pnl_pct = (close / position.entry_price - 1) * 100
                trades.append(
                    PnlTrade(
                        entry_date=position.entry_date,
                        entry_price=round(position.entry_price, 4),
                        entry_action=position.entry_action,
                        exit_date=d,
                        exit_price=round(close, 4),
                        exit_reason="signal_exit",
                        qty=round(position.qty, 6),
                        pnl_pct=round(pnl_pct, 3),
                        pnl_abs=round(pnl_abs, 2),
                        holding_days=(d - position.entry_date).days,
                    )
                )
                cash = proceeds
                position = None

        if position is not None:
            account_value = position.qty * close
            days_in_market += 1
        else:
            account_value = cash
        spy_close = float(spy_price_by_date.get(d, 0))
        spy_value = (
            _PNL_STARTING_CAPITAL * (spy_close / spy_start)
            if spy_start > 0 and spy_close > 0
            else _PNL_STARTING_CAPITAL
        )
        stock_value = stock_baseline_qty * close
        daily_values.append(
            PnlDailyValue(
                date=d,
                strategy_value=round(account_value, 2),
                spy_baseline_value=round(spy_value, 2),
                stock_baseline_value=round(stock_value, 2),
            )
        )

    # End-of-window unwind: close any open position at the last close.
    if position is not None:
        last_close = float(price_by_date[end_date])
        proceeds = position.qty * last_close
        pnl_abs = proceeds - position.qty * position.entry_price
        pnl_pct = (last_close / position.entry_price - 1) * 100
        trades.append(
            PnlTrade(
                entry_date=position.entry_date,
                entry_price=round(position.entry_price, 4),
                entry_action=position.entry_action,
                exit_date=end_date,
                exit_price=round(last_close, 4),
                exit_reason="end_of_window",
                qty=round(position.qty, 6),
                pnl_pct=round(pnl_pct, 3),
                pnl_abs=round(pnl_abs, 2),
                holding_days=(end_date - position.entry_date).days,
            )
        )
        cash = proceeds
        position = None

    final_value = cash
    total_return_pct = (final_value / _PNL_STARTING_CAPITAL - 1) * 100
    spy_end = float(spy_price_by_date.get(end_date, 0))
    spy_total_return = (spy_end / spy_start - 1) * 100 if spy_start > 0 else 0.0
    spy_alpha = total_return_pct - spy_total_return
    stock_end = float(price_by_date[end_date])
    stock_total_return = (
        (stock_end / stock_start - 1) * 100 if stock_start > 0 else 0.0
    )
    stock_alpha = total_return_pct - stock_total_return

    n_trades = len(trades)
    winners = [t for t in trades if t.pnl_pct > 0]
    losers = [t for t in trades if t.pnl_pct < 0]
    win_rate = (len(winners) / n_trades * 100) if n_trades else 0.0
    avg_win = (sum(t.pnl_pct for t in winners) / len(winners)) if winners else 0.0
    avg_loss = (sum(t.pnl_pct for t in losers) / len(losers)) if losers else 0.0

    # Daily returns from mark-to-market values for Sharpe.
    daily_returns: list[float] = []
    for i in range(1, len(daily_values)):
        prev = daily_values[i - 1].strategy_value
        curr = daily_values[i].strategy_value
        if prev > 0:
            daily_returns.append(curr / prev - 1)
    if len(daily_returns) > 1:
        mean_ret = sum(daily_returns) / len(daily_returns)
        var_ret = sum((r - mean_ret) ** 2 for r in daily_returns) / (
            len(daily_returns) - 1
        )
        stdev_ret = var_ret**0.5
        sharpe = (
            (mean_ret / stdev_ret) * (_TRADING_DAYS_PER_YEAR**0.5)
            if stdev_ret > 0
            else 0.0
        )
    else:
        sharpe = 0.0

    # Max drawdown via running peak / trough.
    peak = daily_values[0].strategy_value
    max_dd = 0.0
    for dv in daily_values:
        if dv.strategy_value > peak:
            peak = dv.strategy_value
        if peak > 0:
            dd = (dv.strategy_value - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

    total_days = len(daily_values)
    days_in_market_pct = (
        days_in_market / total_days * 100 if total_days else 0.0
    )

    summary = PnlSummary(
        starting_capital=_PNL_STARTING_CAPITAL,
        final_value=round(final_value, 2),
        total_return_pct=round(total_return_pct, 2),
        spy_total_return_pct=round(spy_total_return, 2),
        spy_alpha_pct=round(spy_alpha, 2),
        stock_total_return_pct=round(stock_total_return, 2),
        stock_alpha_pct=round(stock_alpha, 2),
        n_trades=n_trades,
        n_winners=len(winners),
        n_losers=len(losers),
        win_rate_pct=round(win_rate, 2),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 2),
        days_in_market_pct=round(days_in_market_pct, 2),
    )
    return summary, trades, daily_values


@router.get(
    "/history/pnl-simulation",
    response_model=PnlSimulationResponse,
    summary="Backtest a per-symbol strategy that follows the indicator signals",
)
def pnl_simulation(
    symbol: str = Query(..., min_length=1, max_length=10),
    days: int | None = Query(default=None, ge=30, le=730),
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    snapshots: TickerSnapshotRepository = Depends(get_ticker_snapshot_repository),
    session: Session = Depends(get_db_session),
) -> PnlSimulationResponse:
    validated = validate_symbol_or_raise(symbol)
    if watchlist.get(user_id=user_id, symbol=validated) is None:
        raise NotFoundError(details={"symbol": validated})

    all_snapshots = list(snapshots.list_for_symbol(validated))
    if days is not None and all_snapshots:
        latest = max(s.date for s in all_snapshots)
        cutoff = latest - timedelta(days=days)
        all_snapshots = [s for s in all_snapshots if s.date >= cutoff]

    if not all_snapshots:
        return PnlSimulationResponse(
            symbol=validated,
            days=days,
            summary=_empty_pnl_summary(),
            trades=[],
            daily_values=[],
        )

    stock_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == validated)
        .order_by(DailyPrice.date.asc())
    ).all()
    spy_rows = session.execute(
        select(DailyPrice.date, DailyPrice.close)
        .where(DailyPrice.symbol == _BASELINE_SYMBOL)
        .order_by(DailyPrice.date.asc())
    ).all()
    price_by_date = {r.date: Decimal(str(r.close)) for r in stock_rows}
    spy_price_by_date = {r.date: Decimal(str(r.close)) for r in spy_rows}

    summary, trades, daily_values = _simulate_pnl(
        snapshots=all_snapshots,
        price_by_date=price_by_date,
        spy_price_by_date=spy_price_by_date,
    )
    return PnlSimulationResponse(
        symbol=validated,
        days=days,
        summary=summary,
        trades=trades,
        daily_values=daily_values,
    )

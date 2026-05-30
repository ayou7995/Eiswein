"""Nightly daily_update orchestrator (I6, I7).

Flow:
1. Market calendar gate — skip if today is not an NYSE session.
2. Gap detection — for each watchlist symbol, diff expected NYSE
   sessions (bounded 60 trading days back) against existing DailyPrice
   rows. Produces a per-symbol set of missing dates.
3. ONE bulk yfinance call that covers the widest-needed window across
   all symbols' gap sets. Scheduled runs with zero gaps short-circuit
   here; manual runs still fetch the last trading day so the "立即更新"
   click is never a no-op.
4. UPSERT DailyPrice rows per symbol — **only** for dates in that
   symbol's gap set (or the last trading day on a manual-no-gap run).
   Per-ticker try/except so one symbol failure doesn't abort the job
   (rule 14: graceful degradation).
5. FRED macro fetch (best-effort — failures log + continue).
6. UPSERT MacroIndicator rows.

Not tied to APScheduler — Phase 6 wires the scheduler trigger, this
function is what it calls.

The function is ``async`` and takes a Session and DataSource as
parameters so tests can inject fakes (rule 13: DI).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import structlog

from app.config import Settings
from app.datasources.base import DataSource
from app.datasources.fred_source import DEFAULT_SERIES_IDS, FREDSource
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.macro_repository import MacroRepository, MacroRow
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.calendar_sync import CalendarSyncResult, run_calendar_sync
from app.ingestion.indicators import (
    build_context,
    compute_and_persist,
    compute_and_persist_market_regime,
)
from app.ingestion.locks import get_symbol_lock
from app.ingestion.market_calendar import (
    is_trading_day_et,
    last_trading_day_et,
    now_et,
    nyse_close_at_et,
)
from app.ingestion.persist import iter_daily_price_rows
from app.ingestion.signals import (
    compose_and_persist_market,
    compose_and_persist_ticker,
)
from app.security.exceptions import DataSourceError
from app.services.snapshot_write_mutex import snapshot_write_mutex
from app.signals.types import MarketPosture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.daily")


TriggerMode = Literal["scheduled", "manual", "startup"]

# Triggers that may dispatch the catalyst digest email. Manual button
# clicks suppress the email (the user is already in the app and
# doesn't need an email to themselves). Startup catch-up suppresses
# too — without that gate every container restart, every `make dev`
# auto-reload, every redeploy would send another digest.
_EMAIL_SENDING_TRIGGERS: frozenset[TriggerMode] = frozenset({"scheduled"})

# Trading-day lookback cap for gap detection. 60 ≈ 3 months of
# sessions — deep enough to catch a week-long VM outage but shallow
# enough to bound the yfinance fetch window if the DB is corrupted.
_GAP_LOOKBACK_TRADING_DAYS = 60

# Buffer past NYSE close before a row is considered "settled". Yahoo
# adjustments can lag a few minutes; the 30-min buffer absorbs that.
# Mirrors the constant in market_calendar.py.
_POST_CLOSE_BUFFER_MINUTES = 30

# System symbols fetched on every daily_update regardless of watchlist
# membership. SPY is the SPX proxy every market-regime + relative-
# strength indicator depends on; the migration 0014 seed plus this
# union guarantee a live SPY price series even if no user has SPY on
# their watchlist. Migration 0014 adds SPY to the admin watchlist too —
# this set is the belt against the suspenders of the seed row.
SYSTEM_SYMBOLS: frozenset[str] = frozenset({"SPY"})


@dataclass(frozen=True)
class DailyUpdateResult:
    """Summary returned by ``run_daily_update``. All counts are non-negative.

    ``gaps_filled_rows`` / ``gaps_filled_symbols`` let the API surface
    a "filled N rows across M symbols" note in the manual-refresh
    success banner (Workstream B). A scheduled run that found no gaps
    also reports 0/0 — the scheduler job shortcircuits before fetching.
    """

    market_open: bool
    session_date: date
    symbols_requested: int
    symbols_succeeded: int
    symbols_failed: int
    symbols_delisted: int
    price_rows_upserted: int
    macro_rows_upserted: int
    macro_series_failed: int
    indicators_computed_symbols: int
    indicators_failed_symbols: int
    # Phase 3: composed TickerSnapshot + MarketSnapshot outcomes.
    snapshots_composed: int
    snapshots_failed: int
    market_posture: MarketPosture | None
    # Workstream B (2026-04-21): gap-aware refresh counters. Defaulted
    # to 0 so older test fixtures that construct DailyUpdateResult
    # positionally keep compiling.
    gaps_filled_rows: int = 0
    gaps_filled_symbols: int = 0
    # Phase 7 (Catalyst Calendar): per-source counts and orphan purge
    # from the in-job calendar sync. ``None`` means the sync was
    # skipped or fell back silently (e.g. market closed today).
    calendar: CalendarSyncResult | None = None


async def run_daily_update(
    *,
    db: Session,
    data_source: DataSource,
    settings: Settings,
    trigger: TriggerMode = "scheduled",
) -> DailyUpdateResult:
    """Run the daily ingestion job once.

    Idempotent: safe to re-run the same day — UNIQUE constraints +
    UPSERT keep state stable (rule 12).

    ``trigger`` distinguishes the scheduled nightly job (which
    short-circuits when no gaps are detected) from a manual click on
    "立即更新" (which always fetches at least the last trading day, so
    the user never gets a silent no-op).
    """
    session_day = last_trading_day_et()
    # The "is today a trading day" gate exists so the 06:30 ET cron
    # doesn't burn cycles on Saturdays / Memorial Day / etc. — there's
    # no new data to fetch, the previous scheduled run already covered
    # the last completed session. But manual refreshes and the startup
    # catch-up have the OPPOSITE intent: fill whatever gaps the operator
    # has accumulated, regardless of what today's calendar says. A
    # fresh install on a Saturday must still pull Friday's data — gap
    # detection downstream handles the "nothing to do" branch when
    # everything is already up to date.
    if trigger == "scheduled" and not is_trading_day_et():
        logger.info("daily_update_skipped_market_closed", date=str(session_day))
        return _empty_result(session_day, market_open=False)

    watchlist = WatchlistRepository(db)
    prices = DailyPriceRepository(db)
    macro = MacroRepository(db)

    # Union with SYSTEM_SYMBOLS so SPY is fetched even when no user has
    # added it — indicators that reference the SPX proxy (relative
    # strength, A/D Day Count) would otherwise degrade to
    # data_sufficient=False on a freshly installed system.
    symbols = sorted(set(watchlist.distinct_symbols_across_users()) | SYSTEM_SYMBOLS)
    logger.info(
        "daily_update_start",
        symbols=len(symbols),
        date=str(session_day),
        trigger=trigger,
    )

    price_rows_total = 0
    gaps_filled_rows = 0
    gaps_filled_symbols = 0
    succeeded = 0
    failed = 0
    delisted = 0

    if symbols:
        # Compute per-symbol gaps up front. Bounded lookback prevents a
        # corrupt/empty DB from triggering an unbounded backfill.
        gaps = prices.find_gaps_for_symbols(symbols, lookback_days=_GAP_LOOKBACK_TRADING_DAYS)
        any_gaps = any(dates for dates in gaps.values())

        # Detect partial intra-day rows whose session has already
        # settled. These are dates with an existing row (so gap-detection
        # ignored them) but the row was written before that session's
        # market_close + buffer. Re-fetching now will overwrite the
        # partial bar with the finalized close.
        partials = _find_partial_session_dates(
            prices=prices,
            symbols=symbols,
            lookback_days=_GAP_LOOKBACK_TRADING_DAYS,
            buffer_minutes=_POST_CLOSE_BUFFER_MINUTES,
        )
        any_partials = any(dates for dates in partials.values())

        # Combined "needs work" set: gaps OR partials trigger fetch.
        any_work_needed = any_gaps or any_partials

        if not any_work_needed and trigger == "scheduled":
            logger.debug(
                "daily_update_no_gaps_scheduled_skip",
                date=str(session_day),
                symbols=len(symbols),
            )
            # Still run macro + compose passes — scheduled job owes the
            # nightly indicator / snapshot refresh even if no price rows
            # need filling (e.g., market closed tomorrow but macro moved).
        else:
            # Widest window: from the oldest gap-or-partial date to the
            # last trading day. Manual runs with nothing to do collapse
            # to just session_day.
            combined_dates: dict[str, set[date]] = {
                sym.upper(): set(gaps.get(sym.upper(), [])) | partials.get(sym.upper(), set())
                for sym in symbols
            }
            if any_work_needed:
                oldest_combined = min(
                    (d for s in combined_dates.values() for d in s),
                    default=session_day,
                )
            else:
                oldest_combined = session_day
            start_date = oldest_combined
            end_date = session_day
            period = _period_for_window(start_date=start_date, end_date=end_date)

            try:
                bulk = await data_source.bulk_download(symbols, period=period)
            except DataSourceError as exc:
                logger.warning("daily_update_bulk_failed", details=exc.details)
                bulk = {}

            # When nothing flagged + manual trigger, treat every symbol
            # as needing just ``session_day`` so we persist the latest
            # close but stay idempotent on re-click.
            effective_gaps: dict[str, set[date]] = {
                sym.upper(): (combined_dates[sym.upper()] if any_work_needed else {session_day})
                for sym in symbols
            }

            for sym in symbols:
                frame = bulk.get(sym)
                allowed = effective_gaps.get(sym.upper(), set())
                try:
                    upserted = await _persist_symbol(
                        sym,
                        frame,
                        prices=prices,
                        watchlist=watchlist,
                        allowed_dates=allowed,
                    )
                except DataSourceError as exc:
                    reason = exc.details.get("reason") if isinstance(exc.details, dict) else None
                    if reason == "delisted_or_invalid":
                        delisted += 1
                    else:
                        failed += 1
                    continue
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "daily_update_symbol_failed",
                        symbol=sym,
                        error_type=type(exc).__name__,
                    )
                    logger.debug(
                        "daily_update_symbol_failed_detail",
                        symbol=sym,
                        error=str(exc),
                    )
                    continue
                if upserted == 0:
                    # No rows written — if gaps were expected, count as
                    # a soft failure. The manual-no-gap path also lands
                    # here when yfinance returned no row for session_day
                    # yet (common pre-close) which is benign.
                    if any_work_needed and allowed:
                        failed += 1
                    continue
                price_rows_total += upserted
                if any_gaps and sym.upper() in gaps and gaps[sym.upper()]:
                    gaps_filled_rows += upserted
                    gaps_filled_symbols += 1
                succeeded += 1

            db.commit()

    macro_rows_total, macro_series_failed = await _ingest_macro(
        macro=macro,
        settings=settings,
    )
    db.commit()

    # Phase 2: compute + persist indicators from the freshly-written
    # raw data. Each symbol compute is isolated so one broken ticker
    # doesn't abort the rest (rule 14). Market-regime indicators run
    # once against the SPX frame + macro series.
    # Phase 3: compose + persist signals using the already-in-memory
    # IndicatorResult dicts (avoids a DB round-trip).
    #
    # Snapshot-write mutex held only around the sync compute+persist
    # phase — never across the ``await`` calls above, which would
    # stall the event loop. A concurrent backfill waiting here for
    # the mutex is the intended design.
    with snapshot_write_mutex():
        compute_outcome = _compute_and_compose_for_all(
            db=db,
            symbols=symbols,
            session_day=session_day,
        )

    # Catalyst calendar sync — runs AFTER indicators so any per-ticker
    # earnings proximity logic added in a later commit reads consistent
    # state. Fault-isolated: failures here don't roll back the price /
    # indicator work already persisted. See app.ingestion.calendar_sync
    # for the per-source resilience details.
    calendar_result: CalendarSyncResult | None = None
    try:
        # Sync against the *user-owned* watchlist symbols; SPY is in
        # SYSTEM_SYMBOLS for price fetching but isn't tracked for
        # earnings — including it would create a "SPY Earnings" event
        # because ETFs return a degenerate yfinance calendar row.
        user_symbols = watchlist.distinct_symbols_across_users()
        calendar_result = await run_calendar_sync(
            db,
            watchlist_symbols=list(user_symbols),
            yaml_path=settings.industry_events_yaml or Path("/dev/null"),
            as_of=session_day,
        )
    except Exception as exc:
        logger.warning(
            "daily_update_calendar_sync_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )

    # Catalyst digest email — best-effort. Reads from the calendar
    # table we just synced. Same fault-isolation contract as calendar
    # sync (a flaky relay must not roll back the day's work).
    #
    # ONLY fire from the scheduled APScheduler cron — every other
    # invocation path (manual refresh button, startup catch-up after
    # a `make dev` reload or container restart) suppresses the email.
    # Without this gate the user would receive a fresh digest every
    # time the backend bounces, which in dev is dozens of times a day.
    if trigger in _EMAIL_SENDING_TRIGGERS:
        try:
            _maybe_send_catalyst_digest(db=db, settings=settings, as_of=session_day)
        except Exception as exc:
            logger.warning(
                "daily_update_catalyst_digest_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
    else:
        logger.debug(
            "catalyst_digest_skipped_trigger",
            trigger=trigger,
        )

    logger.info(
        "daily_update_complete",
        date=str(session_day),
        trigger=trigger,
        symbols_requested=len(symbols),
        symbols_succeeded=succeeded,
        symbols_failed=failed,
        symbols_delisted=delisted,
        price_rows=price_rows_total,
        gaps_filled_rows=gaps_filled_rows,
        gaps_filled_symbols=gaps_filled_symbols,
        macro_rows=macro_rows_total,
        indicators_ok=compute_outcome.indicators_ok,
        indicators_failed=compute_outcome.indicators_failed,
        snapshots_composed=compute_outcome.snapshots_ok,
        snapshots_failed=compute_outcome.snapshots_failed,
        market_posture=(
            compute_outcome.market_posture.value
            if compute_outcome.market_posture is not None
            else None
        ),
    )
    return DailyUpdateResult(
        market_open=True,
        session_date=session_day,
        symbols_requested=len(symbols),
        symbols_succeeded=succeeded,
        symbols_failed=failed,
        symbols_delisted=delisted,
        price_rows_upserted=price_rows_total,
        macro_rows_upserted=macro_rows_total,
        macro_series_failed=macro_series_failed,
        indicators_computed_symbols=compute_outcome.indicators_ok,
        indicators_failed_symbols=compute_outcome.indicators_failed,
        snapshots_composed=compute_outcome.snapshots_ok,
        snapshots_failed=compute_outcome.snapshots_failed,
        market_posture=compute_outcome.market_posture,
        gaps_filled_rows=gaps_filled_rows,
        gaps_filled_symbols=gaps_filled_symbols,
        calendar=calendar_result,
    )


def _empty_result(session_day: date, *, market_open: bool) -> DailyUpdateResult:
    """Zero-filled :class:`DailyUpdateResult` for the market-closed path."""
    return DailyUpdateResult(
        market_open=market_open,
        session_date=session_day,
        symbols_requested=0,
        symbols_succeeded=0,
        symbols_failed=0,
        symbols_delisted=0,
        price_rows_upserted=0,
        macro_rows_upserted=0,
        macro_series_failed=0,
        indicators_computed_symbols=0,
        indicators_failed_symbols=0,
        snapshots_composed=0,
        snapshots_failed=0,
        market_posture=None,
        gaps_filled_rows=0,
        gaps_filled_symbols=0,
    )


def _find_partial_session_dates(
    *,
    prices: DailyPriceRepository,
    symbols: list[str],
    lookback_days: int,
    buffer_minutes: int,
) -> dict[str, set[date]]:
    """Per-symbol set of session dates whose stored row is still partial.

    A row is "partial" when:
      * the row's session has already settled (now ≥ close + buffer), AND
      * the row was last written before that session's close + buffer.

    Mid-session rows are excluded — they may legitimately be intra-day
    snapshots that the operator is consciously refreshing; refetching
    would just write another partial bar. Only sessions whose final
    close is now available are flagged for force-refetch.
    """
    if not symbols or lookback_days <= 0:
        return {}
    rows = prices.list_updated_at_for_symbols(symbols, lookback_days=lookback_days)
    if not rows:
        return {}
    now = now_et()
    out: dict[str, set[date]] = {}
    for sym, day, updated_at in rows:
        close = nyse_close_at_et(day)
        if close is None:
            continue  # not a session, can't be partial
        cutoff = close + timedelta(minutes=buffer_minutes)
        if now < cutoff:
            continue  # session not yet settled, refetching wouldn't help
        # Normalize updated_at — repo stores aware UTC, but defensively
        # treat naive as UTC so a legacy migration doesn't crash us.
        row_aware = (
            updated_at
            if updated_at.tzinfo is not None
            else updated_at.replace(tzinfo=ZoneInfo("UTC"))
        )
        if row_aware < cutoff:
            out.setdefault(sym.upper(), set()).add(day)
    return out


def _oldest_gap(gaps: dict[str, list[date]]) -> date:
    """Earliest missing date across every symbol's gap set.

    Caller is expected to have verified ``gaps`` contains at least one
    non-empty entry — we still guard against the empty case so callers
    don't need a defensive check either.
    """
    oldest: date | None = None
    for dates in gaps.values():
        if not dates:
            continue
        candidate = dates[0]  # lists from find_gaps_for_symbols are sorted ascending
        if oldest is None or candidate < oldest:
            oldest = candidate
    if oldest is None:
        # Should not happen when any_gaps is True, but keep the type
        # narrowed and fall back to today_et — yfinance will return the
        # most recent session.
        return last_trading_day_et()
    return oldest


def _period_for_window(*, start_date: date, end_date: date) -> str:
    """yfinance ``period`` string covering the ``[start_date, end_date]`` span.

    The DataSource abstraction speaks ``period`` strings (not
    start/end dates) to stay uniform across providers. We convert the
    calendar span into ``"{N}d"`` and add a small buffer so the
    upstream response definitely covers the oldest gap. Gap-specific
    filtering happens downstream in :func:`_persist_symbol`.
    """
    # Calendar-day span + small buffer so boundary sessions are covered
    # even if yfinance trims the earliest row in its rolling window.
    span_days = max((end_date - start_date).days + 1, 1)
    buffered = span_days + 5
    # Floor at 5 days so the manual-no-gap path doesn't emit "1d"
    # (yfinance's "1d" is intraday — we want a daily bar).
    buffered = max(buffered, 5)
    return f"{buffered}d"


@dataclass(frozen=True)
class _ComputeOutcome:
    """Internal tally for the combined indicator + signal compose pass."""

    indicators_ok: int
    indicators_failed: int
    snapshots_ok: int
    snapshots_failed: int
    market_posture: MarketPosture | None


def _compute_and_compose_for_all(
    *,
    db: Session,
    symbols: list[str],
    session_day: date,
) -> _ComputeOutcome:
    """Compute + persist indicators AND compose + persist signals.

    Order is significant:
    1. Market-regime indicators + :class:`MarketSnapshot` go first so
       each per-ticker compose can reference the current posture.
    2. Per-ticker indicators → per-ticker :class:`TickerSnapshot`.

    Every step is guarded — one broken ticker does not abort the rest
    (rule 14).
    """
    try:
        context = build_context(db=db, today=session_day)
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("indicator_context_build_failed", error=str(exc))
        return _ComputeOutcome(
            indicators_ok=0,
            indicators_failed=len(symbols),
            snapshots_ok=0,
            snapshots_failed=len(symbols),
            market_posture=None,
        )

    # Market regime indicators + posture first.
    market_posture: MarketPosture | None = None
    try:
        regime_results = compute_and_persist_market_regime(session_day, db=db, context=context)
        market_posture = compose_and_persist_market(
            session_day, db=db, regime_results=regime_results
        )
    except Exception as exc:
        logger.warning(
            "market_regime_compose_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        market_posture = None

    effective_posture = market_posture or MarketPosture.NORMAL

    ind_ok = 0
    ind_failed = 0
    snap_ok = 0
    snap_failed = 0
    for sym in symbols:
        try:
            results = compute_and_persist(sym, session_day, db=db, context=context)
        except Exception as exc:
            ind_failed += 1
            snap_failed += 1
            logger.warning(
                "indicator_persist_failed",
                symbol=sym,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            continue
        if not results:
            ind_failed += 1
            snap_failed += 1
            continue
        ind_ok += 1

        try:
            compose_and_persist_ticker(
                sym,
                session_day,
                db=db,
                per_ticker_results=results,
                market_posture=effective_posture,
            )
            snap_ok += 1
        except Exception as exc:
            snap_failed += 1
            logger.warning(
                "signal_compose_failed",
                symbol=sym,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    db.commit()
    return _ComputeOutcome(
        indicators_ok=ind_ok,
        indicators_failed=ind_failed,
        snapshots_ok=snap_ok,
        snapshots_failed=snap_failed,
        market_posture=market_posture,
    )


async def _persist_symbol(
    symbol: str,
    frame: pd.DataFrame | None,
    *,
    prices: DailyPriceRepository,
    watchlist: WatchlistRepository,
    allowed_dates: set[date] | None = None,
) -> int:
    """Persist + update watchlist rows for a single ticker.

    Acquires the per-symbol lock so a concurrent cold-start backfill
    for the same ticker doesn't race the daily job (even though daily
    should be the only writer at 06:30 ET, belt-and-suspenders).

    ``allowed_dates``: when provided, only rows whose date is in the
    set are UPSERTed. The rest of the frame is dropped silently.
    Enables the gap-aware flow to persist exactly the missing days
    without touching already-correct history (idempotency — rule 12).
    Pass ``None`` to accept every row (legacy full-ingest behavior).
    """
    lock = await get_symbol_lock(symbol)
    async with lock:
        if frame is None or frame.empty:
            _mark_watchlist_rows(watchlist, symbol=symbol, status="delisted", mark_refreshed=False)
            raise DataSourceError(details={"reason": "delisted_or_invalid", "symbol": symbol})
        rows = list(iter_daily_price_rows(symbol, frame))
        if allowed_dates is not None:
            if not allowed_dates:
                # Symbol had no gaps on a gap-aware run — persist zero
                # rows but still mark the watchlist row refreshed so
                # the UI knows we visited this ticker.
                _mark_watchlist_rows(watchlist, symbol=symbol, status="ready", mark_refreshed=True)
                return 0
            rows = [r for r in rows if r["date"] in allowed_dates]
        upserted = prices.upsert_many(rows)
        _mark_watchlist_rows(watchlist, symbol=symbol, status="ready", mark_refreshed=True)
        return upserted


def _mark_watchlist_rows(
    watchlist: WatchlistRepository,
    *,
    symbol: str,
    status: str,
    mark_refreshed: bool,
) -> None:
    """Update ``data_status`` for every user that holds this symbol.

    ``distinct_symbols_across_users`` is aggregated — we need the
    per-user rows to update. The ticker is shared master data so every
    user's row lands on the same status.
    """
    now = datetime.now(UTC) if mark_refreshed else None
    for row in watchlist.list_all_for_symbol(symbol):
        row.data_status = status
        if now is not None:
            row.last_refresh_at = now


async def _ingest_macro(
    *,
    macro: MacroRepository,
    settings: Settings,
) -> tuple[int, int]:
    """Fetch default FRED series; log + continue on failure."""
    key = settings.fred_api_key
    if key is None or not key.get_secret_value():
        logger.info("daily_update_macro_skipped_no_key")
        return (0, 0)

    try:
        source = FREDSource(api_key=key.get_secret_value())
    except DataSourceError as exc:
        logger.warning("daily_update_macro_init_failed", details=exc.details)
        return (0, len(DEFAULT_SERIES_IDS))

    try:
        frames = await source.bulk_download(list(DEFAULT_SERIES_IDS))
    except DataSourceError as exc:
        logger.warning("daily_update_macro_bulk_failed", details=exc.details)
        return (0, len(DEFAULT_SERIES_IDS))

    total = 0
    failed = 0
    for series_id, frame in frames.items():
        if frame.empty:
            failed += 1
            continue
        rows: list[MacroRow] = []
        for idx, row in frame.iterrows():
            d = _to_date(idx)
            if d is None:
                continue
            try:
                value = Decimal(str(row["value"]))
            except (InvalidOperation, ValueError):
                continue
            rows.append(MacroRow(series_id=series_id.upper(), date=d, value=value))
        if not rows:
            failed += 1
            continue
        total += macro.upsert_many(rows)
    return (total, failed)


def _to_date(idx: object) -> date | None:
    if isinstance(idx, pd.Timestamp):
        return idx.date()
    if isinstance(idx, date):
        return idx
    try:
        return pd.Timestamp(idx).date()
    except (ValueError, TypeError):
        return None


# Window of upcoming days to summarise in the post-daily-update email.
_CATALYST_DIGEST_HORIZON_DAYS = 3


_LAST_DIGEST_SENT_KEY = "catalyst_digest_last_sent_date"


def _maybe_send_catalyst_digest(
    *,
    db: Session,
    settings: Settings,
    as_of: date,
) -> None:
    """Pull events for [as_of, as_of+horizon) and hand them to the
    catalyst-digest mailer.

    Idempotency: the date of the last successful send is persisted in
    ``system_metadata``. A second invocation on the same day (e.g.
    APScheduler misfire compensation, or two scheduler instances on
    the same DB) sees the metadata row and short-circuits before
    rendering / sending. Belt to the trigger-gating suspenders above.

    The mailer itself no-ops on zero events and on a not-configured
    SMTP relay, so this helper just glues data + send.
    """
    from app.db.repositories.calendar_event_repository import CalendarEventRepository
    from app.db.repositories.system_metadata_repository import SystemMetadataRepository
    from app.jobs.email_dispatcher import send_catalyst_digest

    metadata = SystemMetadataRepository(db)
    last_sent_raw = metadata.get(_LAST_DIGEST_SENT_KEY)
    if last_sent_raw == as_of.isoformat():
        logger.info(
            "catalyst_digest_already_sent_today",
            as_of=str(as_of),
        )
        return

    repo = CalendarEventRepository(db)
    horizon_end = date.fromordinal(as_of.toordinal() + _CATALYST_DIGEST_HORIZON_DAYS - 1)
    events = repo.list_in_range(start=as_of, end=horizon_end)
    if not events:
        return

    sent = send_catalyst_digest(
        events=events,
        as_of=as_of,
        horizon_days=_CATALYST_DIGEST_HORIZON_DAYS,
        settings=settings,
    )
    # Only stamp the "last sent" key on a successful dispatch — a
    # failure (SMTP down, bad creds) shouldn't burn the day's slot.
    if sent:
        metadata.set(_LAST_DIGEST_SENT_KEY, as_of.isoformat())

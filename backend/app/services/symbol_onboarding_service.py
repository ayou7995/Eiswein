"""Symbol onboarding orchestrator (Phase 1 UX overhaul).

A brand-new watchlist entry goes through two phases:

1. **Price cold-start** — ``backfill_ticker`` fetches 2 years of OHLCV
   for the symbol and transitions ``watchlist.data_status`` from
   ``pending`` to ``ready`` (or ``delisted`` / ``failed``).
2. **Snapshot gap-fill** — for every existing ``market_snapshot``
   date, UPSERT the missing ``ticker_snapshot`` row so the user sees
   history identical to a ticker that had been on the watchlist all
   along. Market-regime rows already exist from prior daily_update
   runs, so this is pure per-symbol compute.

Progress is tracked on the same :class:`BackfillJob` table as the
revalidation runner, with ``kind='onboarding'`` and
``symbol=<uppercased symbol>``. The HTTP layer reuses the generic
``GET /api/v1/jobs/{id}`` poll + ``POST /api/v1/jobs/{id}/cancel``
endpoints — there is no onboarding-specific REST surface.

Concurrency
-----------
* Shares the :func:`snapshot_write_mutex` with ``run_daily_update``
  and the revalidation runner so nothing races on
  ``ticker_snapshot`` UPSERTs for the same ``(symbol, date)``.
* ``create_and_start`` refuses to proceed when the repository's
  :meth:`get_active` reports another active job; the watchlist route
  is the only caller and converts that into a 409.
* ``backfill_ticker`` already acquires the per-symbol asyncio lock
  when fetching the initial 2 years of prices — no additional guard
  needed here.

Cancellation
------------
The runner polls ``cancel_requested`` between days in the gap-fill
loop (same pattern as :class:`BackfillService`). When the user DELETEs
a pending watchlist row we flip the flag, and on the next day boundary
the thread exits cleanly. Already-written daily_price + ticker_snapshot
rows are left in place — a re-add reuses them via the gap-fill
short-circuit (skip-if-exists).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.config import Settings
from app.datasources.base import DataSource
from app.db.models import BackfillJob, MarketSnapshot, TickerSnapshot
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.backfill import (
    STATUS_DELISTED,
    STATUS_FAILED,
    STATUS_READY,
    backfill_ticker,
)
from app.ingestion.indicators import build_context, compute_and_persist
from app.ingestion.signals import compose_and_persist_ticker
from app.security.exceptions import ConflictError, DataSourceError
from app.services.snapshot_write_mutex import snapshot_write_mutex
from app.signals.types import MarketPosture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = structlog.get_logger("eiswein.services.onboarding")


class OnboardingAlreadyRunningError(ConflictError):
    """A revalidation job is active so onboarding cannot start.

    Concurrent onboardings are allowed (they queue at
    ``snapshot_write_mutex``); only an active revalidation blocks new
    onboardings. Surfaced by :class:`SymbolOnboardingService.start` —
    the /watchlist POST route catches this and degrades gracefully.
    """

    code = "onboarding_already_running"
    message = "已有一個指標任務正在執行"


class SymbolOnboardingService:
    """Orchestrates end-to-end onboarding for a single new ticker.

    Shares ``session_factory`` + ``snapshot_write_mutex`` with the
    other snapshot writers. Takes a :class:`DataSource` because the
    cold-start fetch needs real yfinance access; in tests the route
    injects a :class:`FakeDataSource` via ``app.state.data_source``.

    ``run_inline`` mirrors :class:`BackfillService` — tests using
    ``StaticPool`` + in-memory SQLite run the thread synchronously so
    the shared connection isn't handed across threads.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        data_source: DataSource,
        run_inline: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._data_source = data_source
        self._run_inline = run_inline

    # --- public API ----------------------------------------------------

    def start(self, *, symbol: str, user_id: int) -> BackfillJob:
        """Create the onboarding ``BackfillJob`` row and spawn the runner.

        The watchlist row for ``symbol`` should already exist with
        ``data_status='pending'`` — the route inserts it before calling
        us so a failed job leaves a visible "pending" row the user can
        see.

        Concurrent onboardings are permitted: the spawned threads block
        at :func:`snapshot_write_mutex` and run one at a time, so a
        user can add many tickers in quick succession and watch them
        complete sequentially. Raises
        :class:`OnboardingAlreadyRunningError` only when a
        ``revalidation`` job is active — revalidation rewrites every
        symbol so it must not interleave with new onboardings.
        """
        normalized = symbol.upper()
        with self._session_factory() as session:
            repo = BackfillJobRepository(session)
            if repo.get_active_for_kind("revalidation") is not None:
                raise OnboardingAlreadyRunningError(details={"symbol": normalized})
            today = datetime.now(UTC).date()
            row = repo.create(
                from_date=today,
                to_date=today,
                force=False,
                user_id=user_id,
                kind="onboarding",
                symbol=normalized,
            )
            session.commit()
            job_id = row.id

        logger.info(
            "onboarding_job_created",
            job_id=job_id,
            symbol=normalized,
            user_id=user_id,
        )

        if self._run_inline:
            self._run(job_id)
        else:
            thread = threading.Thread(
                target=self._run,
                kwargs={"job_id": job_id},
                name=f"onboarding-{job_id}",
                daemon=True,
            )
            thread.start()
        return row

    # --- runner --------------------------------------------------------

    def _run(self, job_id: int) -> None:
        """Thread entry — never re-raises. Mirrors :class:`BackfillService._run`.

        On any unhandled error we mark the job ``failed`` in a fresh
        session and log. If even that fails, the startup orphan-sweep
        catches the row on next boot.
        """
        try:
            with snapshot_write_mutex():
                self._run_with_lock(job_id)
        except Exception as exc:
            logger.warning(
                "onboarding_runner_unhandled",
                job_id=job_id,
                error_type=type(exc).__name__,
            )
            with contextlib.suppress(Exception), self._session_factory() as session:
                BackfillJobRepository(session).update_state(
                    job_id,
                    "failed",
                    error=str(exc),
                )
                session.commit()

    def _run_with_lock(self, job_id: int) -> None:
        """Main onboarding flow: price fetch then per-date snapshot fill.

        The per-day loop polls :meth:`is_cancel_requested` between
        each ``ticker_snapshot`` UPSERT so a watchlist DELETE mid-run
        stops the thread within one snapshot's worth of work.
        """
        # Load the job row + extract scalars we need (symbol, user_id).
        # Done in its own short transaction so the long loop never
        # carries an expired ORM row.
        with self._session_factory() as session:
            repo = BackfillJobRepository(session)
            job = repo.get(job_id)
            if job is None:
                logger.warning("onboarding_runner_missing_row", job_id=job_id)
                return
            if job.state in {"completed", "cancelled", "failed"}:
                logger.info(
                    "onboarding_runner_skipped_terminal",
                    job_id=job_id,
                    state=job.state,
                )
                return
            if not job.symbol:
                # Shouldn't happen — start() sets symbol. Guard so mypy
                # treats the variable as str below and the runner fails
                # loudly instead of silently looping with None.
                repo.update_state(job_id, "failed", error="onboarding_missing_symbol")
                session.commit()
                return
            symbol = job.symbol
            user_id = job.created_by_user_id
            repo.update_state(job_id, "running")
            session.commit()

        logger.info("onboarding_runner_started", job_id=job_id, symbol=symbol)

        # --- Phase 1: price cold-start ---------------------------------
        try:
            self._run_price_cold_start(symbol=symbol, user_id=user_id)
        except DataSourceError as exc:
            reason = exc.details.get("reason") if isinstance(exc.details, dict) else None
            err_code = (
                "delisted_or_invalid" if reason == "delisted_or_invalid" else "data_source_error"
            )
            logger.warning(
                "onboarding_cold_start_failed",
                job_id=job_id,
                symbol=symbol,
                reason=reason,
            )
            self._finalize(
                job_id,
                state="failed",
                error=f"{symbol}: {err_code}",
            )
            return
        except Exception as exc:
            logger.warning(
                "onboarding_cold_start_unhandled",
                job_id=job_id,
                symbol=symbol,
                error_type=type(exc).__name__,
            )
            self._finalize(
                job_id,
                state="failed",
                error=f"{symbol}: {type(exc).__name__}",
            )
            return

        # --- Phase 2: snapshot gap-fill --------------------------------
        dates_to_fill = self._snapshot_dates_missing_for_symbol(symbol)
        with self._session_factory() as session:
            repo = BackfillJobRepository(session)
            # ``total_days`` reflects gap count for progress UX; the UI
            # displays "filled M/N days".
            job = repo.get(job_id)
            if job is not None:
                job.total_days = len(dates_to_fill)
                session.flush()
            session.commit()

        for fill_date in dates_to_fill:
            # Cooperative cancel before each day's work.
            with self._session_factory() as session:
                if BackfillJobRepository(session).is_cancel_requested(job_id):
                    self._finalize(job_id, state="cancelled")
                    logger.info("onboarding_runner_cancelled", job_id=job_id, symbol=symbol)
                    return

            success = self._compose_snapshot_for_date(symbol=symbol, fill_date=fill_date)
            with self._session_factory() as session:
                repo = BackfillJobRepository(session)
                if success:
                    repo.increment_progress(job_id, processed=1)
                else:
                    repo.increment_progress(job_id, failed=1)
                session.commit()

        # Phase 2 done. The watchlist.data_status was already set to
        # 'ready' by backfill_ticker on phase 1 success; revalidate it
        # here in case a transient failure between the two phases left
        # it in a weird state.
        self._mark_watchlist_ready(symbol=symbol, user_id=user_id)
        self._finalize(job_id, state="completed")
        logger.info("onboarding_runner_completed", job_id=job_id, symbol=symbol)

    # --- Phase 1 helper ------------------------------------------------

    def _run_price_cold_start(self, *, symbol: str, user_id: int) -> None:
        """Drive :func:`backfill_ticker` from a sync runner thread.

        ``backfill_ticker`` is async (it owns the per-symbol asyncio
        lock). Two execution contexts have to work:

        1. The **production** path — a dedicated daemon thread spawned
           by :meth:`start`. That thread has no event loop of its own,
           so we create one + run the coroutine to completion.
        2. The **test / inline** path — the route handler calls
           :meth:`start` with ``run_inline=True``, which means we're
           already inside the FastAPI event loop. ``asyncio.run`` or
           ``loop.run_until_complete`` would crash with "loop is
           already running".

        We branch on :func:`asyncio.get_running_loop`. When no loop is
        active (production) a fresh one is created. When a loop is
        running (tests) we spin the coroutine on a one-shot helper
        thread — the calling thread blocks on ``Thread.join`` so
        commit discipline is preserved either way.
        """
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop:
            # Production path — make our own loop for this one call.
            loop = asyncio.new_event_loop()
            try:
                with self._session_factory() as session:
                    loop.run_until_complete(
                        backfill_ticker(
                            symbol,
                            user_id=user_id,
                            db=session,
                            data_source=self._data_source,
                        )
                    )
            finally:
                loop.close()
            return

        # Inline path — we are already inside an event loop, so run the
        # coroutine on a helper thread with its own loop and wait.
        error: list[BaseException] = []

        def _run_in_thread() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                with self._session_factory() as session:
                    loop.run_until_complete(
                        backfill_ticker(
                            symbol,
                            user_id=user_id,
                            db=session,
                            data_source=self._data_source,
                        )
                    )
            except BaseException as exc:
                error.append(exc)
            finally:
                loop.close()

        helper = threading.Thread(
            target=_run_in_thread,
            name=f"onboarding-preflight-{symbol}",
            daemon=True,
        )
        helper.start()
        helper.join()
        if error:
            raise error[0]

    # --- Phase 2 helper ------------------------------------------------

    def _snapshot_dates_missing_for_symbol(self, symbol: str) -> list[date]:
        """``market_snapshot`` dates where ``ticker_snapshot`` has no row.

        Returned ascending (oldest first) so the fill proceeds in
        chronological order and matches the "history filling in" UX
        progression. Bounded by however many market_snapshot rows
        exist — worst case the full app history.
        """
        with self._session_factory() as session:
            market_stmt = select(MarketSnapshot.date).order_by(MarketSnapshot.date.asc())
            market_dates = list(session.execute(market_stmt).scalars())

            existing_stmt = select(TickerSnapshot.date).where(
                TickerSnapshot.symbol == symbol.upper()
            )
            existing = {d for d in session.execute(existing_stmt).scalars()}
        return [d for d in market_dates if d not in existing]

    def _compose_snapshot_for_date(self, *, symbol: str, fill_date: date) -> bool:
        """Compute + persist per-ticker indicator rows and the snapshot.

        Returns True on success, False on any failure (graceful
        degradation: one bad date should not abort the run). A failed
        date is silently counted and does not block later dates — the
        user gets "filled N of M days" in the UI.
        """
        try:
            with self._session_factory() as session:
                market_row = session.execute(
                    select(MarketSnapshot).where(MarketSnapshot.date == fill_date)
                ).scalar_one_or_none()
                if market_row is None:
                    # Shouldn't happen — we derived fill_date from
                    # market_snapshot. Defensive skip so a concurrent
                    # delete (there is none today) wouldn't crash the
                    # runner.
                    return False
                posture = _parse_posture(market_row.posture)

                try:
                    context = build_context(db=session, today=fill_date)
                except Exception as exc:
                    logger.warning(
                        "onboarding_context_failed",
                        symbol=symbol,
                        date=str(fill_date),
                        error_type=type(exc).__name__,
                    )
                    session.rollback()
                    return False

                try:
                    results = compute_and_persist(symbol, fill_date, db=session, context=context)
                except Exception as exc:
                    logger.warning(
                        "onboarding_indicator_failed",
                        symbol=symbol,
                        date=str(fill_date),
                        error_type=type(exc).__name__,
                    )
                    session.rollback()
                    return False
                if not results:
                    # No stored prices on this date (symbol wasn't yet
                    # listed, or the cold-start didn't reach this far
                    # back). Silent skip — the UI's missing-row badge
                    # will show "no data" for that day.
                    session.rollback()
                    return True

                try:
                    compose_and_persist_ticker(
                        symbol,
                        fill_date,
                        db=session,
                        per_ticker_results=results,
                        market_posture=posture,
                    )
                except Exception as exc:
                    logger.warning(
                        "onboarding_compose_failed",
                        symbol=symbol,
                        date=str(fill_date),
                        error_type=type(exc).__name__,
                    )
                    session.rollback()
                    return False
                session.commit()
            return True
        except Exception as exc:
            logger.warning(
                "onboarding_day_unhandled",
                symbol=symbol,
                date=str(fill_date),
                error_type=type(exc).__name__,
            )
            return False

    # --- finalize ------------------------------------------------------

    def _finalize(
        self,
        job_id: int,
        *,
        state: str,
        error: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            BackfillJobRepository(session).update_state(job_id, state, error=error)
            session.commit()

    def _mark_watchlist_ready(self, *, symbol: str, user_id: int) -> None:
        """Set watchlist.data_status='ready' if not already ready.

        ``backfill_ticker`` already flips this on cold-start success,
        so this is a safety net for weird-state recovery. A delete
        mid-run can remove the row entirely — we silently swallow that
        since the job itself is what we finalize here.
        """
        with contextlib.suppress(Exception), self._session_factory() as session:
            repo = WatchlistRepository(session)
            row = repo.get(user_id=user_id, symbol=symbol)
            if row is None:
                return
            if row.data_status not in {STATUS_READY, STATUS_DELISTED, STATUS_FAILED}:
                repo.set_status(
                    user_id=user_id,
                    symbol=symbol,
                    status=STATUS_READY,
                    mark_refreshed=True,
                )
                session.commit()


# --- Helpers --------------------------------------------------------------


def _parse_posture(raw: str) -> MarketPosture:
    """Round-trip the stored posture string through the enum.

    MarketSnapshot.posture is a bare string column; downstream
    ``compose_and_persist_ticker`` requires a :class:`MarketPosture`
    enum. Unknown values (schema drift, manual DB edits) fall back to
    NORMAL — that's the safe default that never biases signals.
    """
    try:
        return MarketPosture(raw)
    except ValueError:
        return MarketPosture.NORMAL


__all__ = (
    "OnboardingAlreadyRunningError",
    "SymbolOnboardingService",
)

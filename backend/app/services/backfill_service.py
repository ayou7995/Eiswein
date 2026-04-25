"""Full-history revalidation orchestrator (service layer).

Single public entry point: :meth:`BackfillService.revalidate_all_snapshots`.
It spawns a runner thread that retro-computes
:class:`DailySignal` + :class:`TickerSnapshot` + :class:`MarketSnapshot`
rows for every trading day from the oldest stored ``market_snapshot``
to today, using already-persisted price + macro data. NO yfinance /
FRED fetch happens inside this runner — data ingestion is the daily
job's responsibility.

Revalidation is fired when ``INDICATOR_VERSION`` drifts past what the
stored rows were computed under. The indicator-drift route
(``POST /api/v1/indicators/revalidate``) is the only caller.

Phase 1 UX overhaul — "backfill" is gone as a user concept. The
historical read-only ``plan()`` + user-configurable range ``start()``
endpoints are deleted; there's nothing to plan anymore because the
range is always "everything in history". Onboarding jobs use a
separate service (:class:`SymbolOnboardingService`) and share only the
:class:`BackfillJob` table + the :func:`snapshot_write_mutex`.

Runner invariants
-----------------
* Strict **ascending date** iteration — :class:`TickerSnapshot`
  embeds ``market_posture_at_compute`` so the market row for day ``D``
  must land before any ticker row for day ``D``.
* Each day is a per-day commit — a crash mid-run leaves a consistent
  DB; re-running (with ``force=True`` as the revalidation constant)
  rewrites all affected rows.
* Symbol selection uses the **current** watchlist; SPY is pinned so
  the system benchmark is always recomputed.
* Startup cleanup hook :func:`mark_orphaned_backfills_failed` runs in
  app lifespan: any ``running``/``pending`` row left by a previous
  process crash is flipped to ``failed`` so ``get_active()`` doesn't
  report a phantom in-flight job.
* :func:`app.services.snapshot_write_mutex.snapshot_write_mutex` held
  during the per-day compute loop so revalidation never interleaves
  with ``run_daily_update``'s snapshot write phase.
"""

from __future__ import annotations

import contextlib
import threading
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, func, select, update

from app.config import Settings
from app.db.models import (
    BackfillJob,
    DailySignal,
    MarketSnapshot,
    TickerSnapshot,
)
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.daily_ingestion import SYSTEM_SYMBOLS
from app.ingestion.indicators import (
    build_context,
    compute_and_persist,
    compute_and_persist_market_regime,
)
from app.ingestion.market_calendar import get_trading_days, today_et
from app.ingestion.signals import (
    compose_and_persist_market,
    compose_and_persist_ticker,
)
from app.ingestion.streak_rebuild import rebuild_streak_table
from app.security.exceptions import ConflictError
from app.services.snapshot_write_mutex import snapshot_write_mutex
from app.signals.types import MarketPosture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = structlog.get_logger("eiswein.services.backfill")


# --- Errors ---------------------------------------------------------------


class BackfillAlreadyRunningError(ConflictError):
    """Raised when :meth:`BackfillService.revalidate_all_snapshots` is
    invoked while another job (revalidation OR onboarding) is already
    pending / running.
    """

    code = "backfill_already_running"
    message = "已有一個指標任務正在執行"


# --- Service --------------------------------------------------------------


class BackfillService:
    """Orchestrator for full-history indicator revalidation.

    Constructed via :func:`app.api.v1.indicators_routes._build_service`;
    the HTTP handler feeds it the shared session factory + settings.

    ``run_inline=True`` runs the worker on the caller's thread instead
    of spawning a new one. Intended for tests using SQLAlchemy's
    ``StaticPool`` + in-memory SQLite where the shared single connection
    is race-prone across threads.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        run_inline: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._run_inline = run_inline

    # --- revalidate_all_snapshots --------------------------------------

    def revalidate_all_snapshots(self, *, user_id: int) -> BackfillJob:
        """Create + start a full-history revalidation job.

        Range: oldest stored ``market_snapshot`` date to today. If no
        market_snapshot rows exist yet (fresh install), the range
        collapses to ``(today, today)`` — the runner no-ops immediately
        and the UI sees ``total_days=0, state=completed``.
        """
        today = today_et()
        with self._session_factory() as session:
            repo = BackfillJobRepository(session)
            if repo.get_active() is not None:
                raise BackfillAlreadyRunningError()

            oldest = session.execute(select(func.min(MarketSnapshot.date))).scalar_one_or_none()
            from_date = oldest if oldest is not None else today

            row = repo.create(
                from_date=from_date,
                to_date=today,
                force=True,
                user_id=user_id,
                kind="revalidation",
                symbol=None,
            )
            session.commit()
            job_id = row.id

        logger.info(
            "revalidation_job_created",
            job_id=job_id,
            from_date=from_date.isoformat(),
            to_date=today.isoformat(),
        )

        if self._run_inline:
            self._run(job_id)
        else:
            thread = threading.Thread(
                target=self._run,
                kwargs={"job_id": job_id},
                name=f"revalidate-{job_id}",
                daemon=True,
            )
            thread.start()
        return row

    # --- runner --------------------------------------------------------

    def _run(self, job_id: int) -> None:
        """Thread entry point. Never re-raises — it's terminal.

        On any unhandled error we attempt to mark the job ``failed`` in
        a fresh session and log. If even *that* fails, the startup
        orphan sweep catches the row on next boot.
        """
        try:
            with snapshot_write_mutex():
                self._run_with_lock(job_id)
        except Exception as exc:
            logger.warning(
                "revalidation_runner_unhandled",
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
        """Main per-day loop, executed under :func:`snapshot_write_mutex`."""
        logger.info("revalidation_runner_started", job_id=job_id)

        with self._session_factory() as session:
            repo = BackfillJobRepository(session)
            job = repo.get(job_id)
            if job is None:
                logger.warning("revalidation_runner_missing_row", job_id=job_id)
                return
            if job.state in _TERMINAL_STATES:
                logger.info(
                    "revalidation_runner_skipped_terminal",
                    job_id=job_id,
                    state=job.state,
                )
                return
            from_date = job.from_date
            to_date = job.to_date
            force = job.force
            trading_days = get_trading_days(from_date, to_date)
            job.total_days = len(trading_days)
            repo.update_state(job_id, "running")
            session.commit()

        logger.info(
            "revalidation_runner_loop_start",
            job_id=job_id,
            total_days=len(trading_days),
            force=force,
        )

        with self._session_factory() as bootstrap_session:
            watchlist_symbols = set(
                WatchlistRepository(bootstrap_session).distinct_symbols_across_users()
            )
        symbols = sorted(watchlist_symbols | SYSTEM_SYMBOLS)

        with self._session_factory() as session:
            repo = BackfillJobRepository(session)

            if not symbols or not trading_days:
                logger.info(
                    "revalidation_runner_nothing_to_do",
                    job_id=job_id,
                    total_days=len(trading_days),
                    symbols=len(symbols),
                )
                if trading_days:
                    repo.increment_progress(job_id, skipped=len(trading_days))
                repo.update_state(job_id, "completed")
                session.commit()
                logger.info("revalidation_runner_completed", job_id=job_id)
                return

            for session_day in trading_days:
                if repo.is_cancel_requested(job_id):
                    repo.update_state(job_id, "cancelled")
                    session.commit()
                    logger.info("revalidation_runner_cancelled", job_id=job_id)
                    return

                if not force and _has_existing_market_snapshot(session, session_day):
                    repo.increment_progress(job_id, skipped=1)
                    session.commit()
                    continue

                if force:
                    _delete_day_rows(
                        session,
                        session_day=session_day,
                        symbols=symbols,
                    )

                try:
                    context = build_context(db=session, today=session_day)
                except Exception as exc:
                    logger.warning(
                        "revalidation_context_failed",
                        job_id=job_id,
                        symbol_count=len(symbols),
                        error_type=type(exc).__name__,
                    )
                    session.rollback()
                    repo.increment_progress(job_id, failed=1)
                    session.commit()
                    continue

                try:
                    regime_results = compute_and_persist_market_regime(
                        session_day,
                        db=session,
                        context=context,
                    )
                    market_posture = compose_and_persist_market(
                        session_day,
                        db=session,
                        regime_results=regime_results,
                    )
                except Exception as exc:
                    logger.warning(
                        "revalidation_market_failed",
                        job_id=job_id,
                        error_type=type(exc).__name__,
                    )
                    session.rollback()
                    repo.increment_progress(job_id, failed=1)
                    session.commit()
                    continue

                effective_posture = market_posture or MarketPosture.NORMAL

                for sym in symbols:
                    try:
                        per_ticker_results = compute_and_persist(
                            sym,
                            session_day,
                            db=session,
                            context=context,
                        )
                        if not per_ticker_results:
                            continue
                        compose_and_persist_ticker(
                            sym,
                            session_day,
                            db=session,
                            per_ticker_results=per_ticker_results,
                            market_posture=effective_posture,
                        )
                    except Exception as exc:
                        logger.warning(
                            "revalidation_symbol_failed",
                            job_id=job_id,
                            error_type=type(exc).__name__,
                        )
                        continue

                session.commit()
                repo.increment_progress(job_id, processed=1)
                session.commit()

            try:
                rebuild_streak_table(db=session, from_date=from_date)
                session.commit()
            except Exception as exc:
                logger.warning(
                    "revalidation_streak_rebuild_failed",
                    job_id=job_id,
                    error_type=type(exc).__name__,
                )
                session.rollback()

            repo.update_state(job_id, "completed")
            session.commit()
            logger.info("revalidation_runner_completed", job_id=job_id)


# --- Module-level helpers -------------------------------------------------


_TERMINAL_STATES = frozenset({"completed", "cancelled", "failed"})


def _has_existing_market_snapshot(session: Session, d: date) -> bool:
    stmt = select(MarketSnapshot.id).where(MarketSnapshot.date == d).limit(1)
    return session.execute(stmt).scalar_one_or_none() is not None


def _delete_day_rows(
    session: Session,
    *,
    session_day: date,
    symbols: list[str],
) -> None:
    """Hard-delete existing rows for the (date, symbols + SPY) tuple.

    Revalidation always runs with ``force=True``, so this is called on
    every non-skipped day: nuke the old rows, then re-compute + insert.
    """
    upper_symbols = [s.upper() for s in symbols]
    session.execute(delete(MarketSnapshot).where(MarketSnapshot.date == session_day))
    session.execute(
        delete(TickerSnapshot).where(
            TickerSnapshot.date == session_day,
            TickerSnapshot.symbol.in_(upper_symbols),
        )
    )
    session.execute(
        delete(DailySignal).where(
            DailySignal.date == session_day,
            DailySignal.symbol.in_([*upper_symbols, "SPY"]),
        )
    )


def mark_orphaned_backfills_failed(*, session: Session) -> int:
    """Startup recovery — flip any ``pending`` / ``running`` row to ``failed``.

    Called from ``app.main`` lifespan on every boot. Covers jobs that
    were left mid-flight when the previous process died. Without this
    step the DB row stays active and
    :meth:`BackfillJobRepository.get_active` would permanently refuse
    new jobs.

    Returns the number of rows flipped. Caller owns the transaction.
    """
    now = datetime.now(UTC)
    stmt = (
        update(BackfillJob)
        .where(BackfillJob.state.in_(("pending", "running")))
        .values(
            state="failed",
            error="orphaned_by_restart",
            finished_at=now,
        )
    )
    result = session.execute(stmt)
    rowcount = result.rowcount or 0
    if rowcount:
        logger.warning("backfill_orphans_reaped", rows=rowcount)
    return int(rowcount)


__all__ = (
    "BackfillAlreadyRunningError",
    "BackfillService",
    "mark_orphaned_backfills_failed",
)

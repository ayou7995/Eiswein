"""Daily-update scheduled job wrapper (Phase 6).

Wraps :func:`app.ingestion.daily_ingestion.run_daily_update` so the
scheduler can fire it on a cron trigger without depending on the
ingestion module directly. Adds three concerns:

* Persists ``last_daily_update_at`` to :class:`SystemMetadata` on
  successful (market-open) runs — surfaced by the ``/settings/system-info``
  endpoint.
* Dispatches the daily summary email via :mod:`email_dispatcher`.
* On ``market_open=False`` skips both the email and the metadata
  update (nothing changed, nothing to announce).

Exceptions are caught so a scheduler tick never aborts because of one
bad job (rule 14). They are logged with the ``job_name`` field so
observability stays tied together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.datasources.base import DataSource
from app.db.repositories.system_metadata_repository import (
    KEY_LAST_DAILY_UPDATE_AT,
    SystemMetadataRepository,
)
from app.db.repositories.ticker_snapshot_repository import TickerSnapshotRepository
from app.ingestion.daily_ingestion import DailyUpdateResult, run_daily_update
from app.jobs.email_dispatcher import TickerSummaryRow, send_daily_summary

logger = structlog.get_logger("eiswein.jobs.daily_update")

JOB_NAME = "daily_update"


async def run(
    *,
    session_factory: sessionmaker[Session],
    data_source: DataSource,
    settings: Settings,
) -> DailyUpdateResult | None:
    """Execute one daily_update cycle.

    Dependency injection: caller passes the session factory + data
    source so a test can swap both without touching the scheduler
    wiring. Returns the :class:`DailyUpdateResult` on success (even a
    market-closed short-circuit counts as success) and ``None`` when
    the underlying job raised — the scheduler keeps running in
    either case.
    """
    logger.info("job_start", job_name=JOB_NAME)

    try:
        with session_factory() as session:
            result = await run_daily_update(
                db=session,
                data_source=data_source,
                settings=settings,
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    if not result.market_open:
        logger.info("job_skipped", job_name=JOB_NAME, reason="market_closed")
        return result

    # Persist the "last run at" timestamp + dispatch the email. Each
    # side-channel has its own try/except so a flaky email relay
    # doesn't mask the metadata write.
    _record_last_update(
        session_factory=session_factory,
        when=datetime.now(UTC),
    )
    _dispatch_email(
        session_factory=session_factory,
        result=result,
        settings=settings,
    )

    logger.info(
        "job_complete",
        job_name=JOB_NAME,
        session_date=str(result.session_date),
        symbols_succeeded=result.symbols_succeeded,
        symbols_failed=result.symbols_failed,
    )
    return result


def _record_last_update(
    *,
    session_factory: sessionmaker[Session],
    when: datetime,
) -> None:
    try:
        with session_factory() as session:
            SystemMetadataRepository(session).set_datetime(KEY_LAST_DAILY_UPDATE_AT, when)
            session.commit()
    except Exception as exc:
        logger.warning(
            "metadata_write_failed",
            job_name=JOB_NAME,
            key=KEY_LAST_DAILY_UPDATE_AT,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def _dispatch_email(
    *,
    session_factory: sessionmaker[Session],
    result: DailyUpdateResult,
    settings: Settings,
) -> None:
    snapshots: list[TickerSummaryRow]
    try:
        with session_factory() as session:
            # TickerSnapshot satisfies the TickerSummaryRow Protocol by
            # attribute shape; the Protocol lives in email_dispatcher to
            # avoid coupling the email module to SQLAlchemy directly.
            # mypy can't verify structural conformance across a
            # SQLAlchemy Mapped[...] column → plain attribute mapping,
            # so the cast pins the intended typing contract.
            rows = TickerSnapshotRepository(session).list_for_date(result.session_date)
            snapshots = cast(list[TickerSummaryRow], list(rows))
    except Exception as exc:
        logger.warning(
            "email_snapshot_load_failed",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        snapshots = []

    try:
        send_daily_summary(
            result=result,
            snapshots=snapshots,
            settings=settings,
        )
    except Exception as exc:  # email dispatcher never raises, but belt-and-suspenders
        logger.warning(
            "email_dispatch_raised",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )

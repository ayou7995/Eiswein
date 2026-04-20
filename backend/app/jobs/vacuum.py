"""Monthly VACUUM maintenance job (Phase 6, I15).

Runs on the first Sunday of each month at 03:00 ET (scheduler cron).
Extra safety: the job consults ``system_metadata['last_vacuum_at']``
and short-circuits if it ran within the last 25 days. That way the
cron trigger firing twice (e.g. two container restarts within the
window) does not cause a back-to-back VACUUM.

Why full VACUUM + not just ``PRAGMA incremental_vacuum``
-------------------------------------------------------
``PRAGMA auto_vacuum=INCREMENTAL`` is set at connection time, which
releases freed pages incrementally as writes happen. Periodic full
VACUUM still helps when large deletions fragment the file badly
(e.g. MacroIndicator cleanup). Running monthly keeps the file lean
without thrashing I/O.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.system_metadata_repository import (
    KEY_LAST_VACUUM_AT,
    SystemMetadataRepository,
)

logger = structlog.get_logger("eiswein.jobs.vacuum")

JOB_NAME = "vacuum"

_VACUUM_COOLDOWN_DAYS = 25


async def run(
    *,
    engine: Engine,
    session_factory: sessionmaker[Session],
    cooldown: timedelta = timedelta(days=_VACUUM_COOLDOWN_DAYS),
    clock: type[datetime] = datetime,
) -> bool:
    """Run VACUUM if we're past the cooldown.

    Returns ``True`` when VACUUM ran, ``False`` when skipped or failed.
    Never raises (scheduler protocol).
    """
    logger.info("job_start", job_name=JOB_NAME)

    now = clock.now(UTC)

    try:
        with session_factory() as session:
            last = SystemMetadataRepository(session).get_datetime(KEY_LAST_VACUUM_AT)
    except Exception as exc:
        logger.warning(
            "metadata_read_failed",
            job_name=JOB_NAME,
            key=KEY_LAST_VACUUM_AT,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        last = None

    if last is not None and (now - last) < cooldown:
        logger.info(
            "job_skipped",
            job_name=JOB_NAME,
            reason="cooldown",
            last_vacuum_at=last.isoformat(),
            days_since=round((now - last).total_seconds() / 86400, 2),
        )
        return False

    size_before = _db_size(engine)
    t0 = time.perf_counter()
    try:
        # VACUUM cannot run inside a transaction. Acquire a connection
        # with AUTOCOMMIT isolation BEFORE any implicit BEGIN is
        # issued — ``connect().execution_options(...)`` must happen
        # on a fresh connection so SQLAlchemy's 2.x autobegin doesn't
        # open a txn first.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("VACUUM")
    except Exception as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False

    duration_ms = int((time.perf_counter() - t0) * 1000)
    size_after = _db_size(engine)
    logger.info(
        "job_complete",
        job_name=JOB_NAME,
        size_before_bytes=size_before,
        size_after_bytes=size_after,
        duration_ms=duration_ms,
    )

    try:
        with session_factory() as session:
            SystemMetadataRepository(session).set_datetime(KEY_LAST_VACUUM_AT, now)
            session.commit()
    except Exception as exc:
        logger.warning(
            "metadata_write_failed",
            job_name=JOB_NAME,
            key=KEY_LAST_VACUUM_AT,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    return True


def _db_size(engine: Engine) -> int | None:
    if engine.url.get_backend_name() != "sqlite":
        return None
    db = engine.url.database
    if db is None or db == ":memory:" or not db:
        return None
    try:
        return Path(db).stat().st_size
    except OSError:
        return None

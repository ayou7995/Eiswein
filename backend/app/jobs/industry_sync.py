"""Weekly Gemini-backed industry catalyst sync job.

Wrapper around :func:`app.ingestion.industry_gemini_sync.run_industry_gemini_sync`
that conforms to the APScheduler ``run(**kwargs)`` contract used by the
rest of the jobs in this package.

Scheduled cadence (registered by :func:`app.jobs.scheduler._register_jobs`)
is Sunday 10:00 ET — market closed, weekend so the freshest catch is
available for the Monday-morning open. The admin manual-trigger endpoint
calls :mod:`app.ingestion.industry_gemini_sync` directly (not this
wrapper) so it can return a structured response synchronously.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.industry_gemini_sync import run_industry_gemini_sync

logger = structlog.get_logger("eiswein.jobs.industry_sync")

JOB_NAME = "industry_sync"


async def run(
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> bool:
    """Pull the Gemini industry sync into the DB. Returns True on a
    successful execution (even if rows == 0); False on skip / error.

    Never raises — scheduler protocol. The ingestion layer already
    catches LLM errors and returns ``skipped_reason``; this wrapper just
    persists the session and decides the boolean return."""
    logger.info("job_start", job_name=JOB_NAME)

    api_key_secret = settings.gemini_api_key
    api_key = api_key_secret.get_secret_value() if api_key_secret else ""

    try:
        with session_factory() as session:
            result = await run_industry_gemini_sync(session, api_key=api_key)
            session.commit()
    except Exception as exc:
        logger.warning(
            "industry_sync_job_failed",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False

    if result.skipped_reason is not None:
        logger.info(
            "job_complete",
            job_name=JOB_NAME,
            skipped=result.skipped_reason,
        )
        return False

    logger.info(
        "job_complete",
        job_name=JOB_NAME,
        events_returned=result.events_returned,
        rows_upserted=result.rows_upserted,
    )
    return True

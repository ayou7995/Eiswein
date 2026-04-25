"""Proactive Schwab refresh-token rotation (Phase S1).

Scheduled via APScheduler every 20 minutes (see
:func:`app.jobs.scheduler.start_scheduler`). For each stored
``BrokerCredential(broker='schwab')`` row:

* If a cached access token for that user is still healthy (> 60s until
  expiry) this is a no-op. Otherwise we fire ``POST /oauth/token`` with
  the ``refresh_token`` grant.
* On success: write through the possibly-rotated refresh token, cache
  the new access token, and stamp ``last_refreshed_at``.
* On ``invalid_grant``: the refresh token is past its 7-day TTL or was
  revoked. Delete the row (``get_or_refresh_access_token`` already does
  this inside the helper). A later UI load surfaces "disconnected".
* On network errors: log a warning and move on — next tick in 20 min.

Why counts-only logs
--------------------
We never log token bodies or user identifiers beyond the integer
``user_id``. The refresh cadence is the same for everyone (every 20m),
so aggregate counts make ops dashboards useful without leaking
per-user behavior.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.datasources.schwab_oauth import SchwabOAuthError
from app.db.models import BrokerCredential
from app.services.schwab_session import (
    SchwabReauthRequired,
    get_or_refresh_access_token,
)

logger = structlog.get_logger("eiswein.jobs.schwab_token_refresh")

JOB_NAME = "schwab_token_refresh"


async def run(
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> dict[str, int]:
    """Execute one refresh pass across every Schwab credential.

    Returns a summary dict so tests can assert counts without
    inspecting logs. Never raises — individual failures are swallowed
    so one bad credential doesn't stop the others.
    """
    logger.info("job_start", job_name=JOB_NAME)

    if not settings.schwab_enabled:
        logger.info("job_skipped", job_name=JOB_NAME, reason="schwab_not_configured")
        return {"users_refreshed": 0, "users_failed": 0, "users_reauth_required": 0}

    user_ids = _collect_user_ids(session_factory)
    if not user_ids:
        logger.info("job_skipped", job_name=JOB_NAME, reason="no_schwab_credentials")
        return {"users_refreshed": 0, "users_failed": 0, "users_reauth_required": 0}

    counts = {"users_refreshed": 0, "users_failed": 0, "users_reauth_required": 0}
    for uid in user_ids:
        try:
            await get_or_refresh_access_token(
                user_id=uid,
                session_factory=session_factory,
                settings=settings,
            )
        except SchwabReauthRequired:
            counts["users_reauth_required"] += 1
        except SchwabOAuthError as exc:
            # Network error or unexpected upstream failure — skip and
            # try again on next tick.
            counts["users_failed"] += 1
            logger.warning(
                "schwab_refresh_failed",
                job_name=JOB_NAME,
                user_id=uid,
                error_code=exc.code,
            )
        except Exception as exc:
            # Defensive catch: the job must never take the scheduler
            # down. Log with the type name so we can audit unknowns.
            counts["users_failed"] += 1
            logger.warning(
                "schwab_refresh_unexpected",
                job_name=JOB_NAME,
                user_id=uid,
                error_type=type(exc).__name__,
            )
        else:
            counts["users_refreshed"] += 1

    logger.info("job_complete", job_name=JOB_NAME, **counts)
    return counts


def _collect_user_ids(session_factory: sessionmaker[Session]) -> list[int]:
    with session_factory() as session:
        stmt = select(BrokerCredential.user_id).where(BrokerCredential.broker == "schwab")
        return [int(uid) for uid in session.execute(stmt).scalars().all()]


# Alias exposed under the name the task plan refers to. Keeps
# compatibility both with ``schwab_token_refresh.run(...)`` (used by the
# scheduler wrapper) and the plan-level handle
# ``refresh_all_schwab_tokens`` used in ops notes / smoke checks.
refresh_all_schwab_tokens = run


__all__: tuple[str, ...] = ("JOB_NAME", "refresh_all_schwab_tokens", "run")

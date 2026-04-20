"""Broker refresh-token expiry reminder job (Phase 6, I14).

Scans ``BrokerCredential.expires_at`` for any row with ``<=2 days``
remaining and sends a single alert email per expiring row. The
Schwab OAuth integration proper lands in a later phase — until then,
this job is a no-op on the empty table (the log line makes that
visible).

The dedup story is intentionally simple for v1:

* The scheduler ticks once a day, so one alert per credential per
  day is fine.
* We don't persist an "alert_sent_at" column yet — if a user lets
  the token continue to expire for three days, they get three
  reminders. Acceptable for a single-user personal tool.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import BrokerCredential
from app.jobs.email_dispatcher import send_token_expiry_alert

logger = structlog.get_logger("eiswein.jobs.token_reminder")

JOB_NAME = "token_reminder"

_WARNING_WINDOW = timedelta(days=2)


async def run(
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
    window: timedelta = _WARNING_WINDOW,
    clock: type[datetime] = datetime,
) -> int:
    """Send alerts for credentials expiring within ``window``.

    Returns the number of alerts successfully dispatched (0 when
    there are no credentials or when email is not configured).
    Never raises.
    """
    logger.info("job_start", job_name=JOB_NAME)

    try:
        with session_factory() as session:
            rows = _collect_expiring(session=session, window=window, now=clock.now(UTC))
    except Exception as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 0

    if not rows:
        # Distinguish "no credentials at all" (pre-Schwab integration)
        # from "credentials exist but none expiring soon" for ops
        # visibility.
        logger.info("job_skipped", job_name=JOB_NAME, reason="no_expiring_credentials")
        return 0

    sent = 0
    now = clock.now(UTC)
    for cred in rows:
        if cred.expires_at is None:
            continue
        expires_at = _ensure_utc(cred.expires_at)
        days_remaining = max((expires_at - now).days, 0)
        ok = send_token_expiry_alert(
            days_remaining=days_remaining,
            expires_at=expires_at,
            broker=cred.broker,
            settings=settings,
        )
        if ok:
            sent += 1

    logger.info(
        "job_complete",
        job_name=JOB_NAME,
        expiring_credentials=len(rows),
        emails_sent=sent,
    )
    return sent


def _collect_expiring(
    *,
    session: Session,
    window: timedelta,
    now: datetime,
) -> list[BrokerCredential]:
    threshold = now + window
    stmt = select(BrokerCredential).where(
        BrokerCredential.expires_at.is_not(None),
        BrokerCredential.expires_at <= threshold,
    )
    return list(session.execute(stmt).scalars().all())


def _ensure_utc(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)

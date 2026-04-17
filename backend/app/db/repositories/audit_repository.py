"""Audit log writer + queryable history.

Append-only by convention (I9). Methods that would mutate or delete a
row are intentionally absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.security.login_throttle import AttemptRecord

LOGIN_SUCCESS = "login.success"
LOGIN_FAILURE = "login.failure"
LOGIN_LOCKOUT = "login.lockout"
LOGOUT = "logout"
TOKEN_REFRESH = "token.refresh"
PASSWORD_CHANGED = "password.changed"


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        event_type: str,
        *,
        user_id: int | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            event_type=event_type,
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            details=details,
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def recent_login_attempts(
        self, *, window: timedelta, now: datetime | None = None
    ) -> Sequence[AttemptRecord]:
        current = now or datetime.now(timezone.utc)
        cutoff = current - window
        stmt = (
            select(AuditLog)
            .where(AuditLog.event_type.in_([LOGIN_SUCCESS, LOGIN_FAILURE]))
            .where(AuditLog.timestamp >= cutoff)
            .order_by(AuditLog.timestamp.desc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [
            AttemptRecord(
                ip=row.ip or "",
                success=row.event_type == LOGIN_SUCCESS,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

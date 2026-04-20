"""Audit log writer + queryable history.

Append-only by convention (I9). Methods that would mutate or delete a
row are intentionally absent.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

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
MANUAL_DATA_REFRESH = "data.manual_refresh"
POSITION_OPENED = "position.opened"
POSITION_CLOSED = "position.closed"
POSITION_ADD = "position.add"
POSITION_REDUCE = "position.reduce"


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
        current = now or datetime.now(UTC)
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

    def list_for_user(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> Sequence[AuditLog]:
        """User-scoped audit log read — most recent first.

        ``user_id`` filter is critical: never return another user's
        entries. ``details`` is passed through as-is; the route layer
        sanitises any field names we don't want leaked (e.g.
        ``password``). The log sanitizer already redacts sensitive
        values in structlog output; this path targets stored rows.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .limit(max(1, min(limit, 500)))
        )
        return self._session.execute(stmt).scalars().all()

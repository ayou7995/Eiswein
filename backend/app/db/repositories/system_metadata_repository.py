"""Key-value store for cross-job scheduler state (Phase 6).

Values are stored as short strings. The repository also exposes
datetime helpers — callers that track "last run at" timestamps avoid
re-implementing ISO-8601 (de)serialization at each callsite.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemMetadata


class SystemMetadataRepository:
    """Thin wrapper around :class:`SystemMetadata` rows.

    ``set`` performs an upsert (insert-or-update) in a single flush so
    repeated writes to the same key don't accumulate duplicate rows.
    ISO-8601 helpers ``set_datetime`` / ``get_datetime`` preserve tzinfo
    across round-trips (stored as UTC).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str) -> str | None:
        stmt = select(SystemMetadata).where(SystemMetadata.key == key)
        row = self._session.execute(stmt).scalar_one_or_none()
        return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        stmt = select(SystemMetadata).where(SystemMetadata.key == key)
        existing = self._session.execute(stmt).scalar_one_or_none()
        if existing is None:
            self._session.add(SystemMetadata(key=key, value=value))
        else:
            existing.value = value
            existing.updated_at = datetime.now(UTC)
        self._session.flush()

    def get_datetime(self, key: str) -> datetime | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def set_datetime(self, key: str, when: datetime) -> None:
        aware = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
        self.set(key, aware.isoformat())


# Well-known metadata keys (single source of truth so a typo in one
# caller doesn't shadow writes from another).
KEY_LAST_DAILY_UPDATE_AT = "last_daily_update_at"
KEY_LAST_BACKUP_AT = "last_backup_at"
KEY_LAST_VACUUM_AT = "last_vacuum_at"

"""Tests for :class:`SystemMetadataRepository`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import SystemMetadata
from app.db.repositories.system_metadata_repository import (
    KEY_LAST_BACKUP_AT,
    KEY_LAST_DAILY_UPDATE_AT,
    KEY_LAST_VACUUM_AT,
    SystemMetadataRepository,
)


def test_get_returns_none_for_missing_key(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    assert repo.get("missing") is None
    assert repo.get_datetime("missing") is None


def test_set_then_get_round_trip(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    repo.set("custom_key", "hello")
    db_session.commit()

    assert repo.get("custom_key") == "hello"


def test_set_is_upsert_not_duplicate(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    repo.set(KEY_LAST_BACKUP_AT, "v1")
    repo.set(KEY_LAST_BACKUP_AT, "v2")
    repo.set(KEY_LAST_BACKUP_AT, "v3")
    db_session.commit()

    assert repo.get(KEY_LAST_BACKUP_AT) == "v3"

    # Only one row for the key.
    rows = (
        db_session.execute(
            sa.select(SystemMetadata).where(SystemMetadata.key == KEY_LAST_BACKUP_AT)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_datetime_helpers_preserve_utc(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    moment = datetime(2026, 4, 19, 12, 30, 15, tzinfo=UTC)
    repo.set_datetime(KEY_LAST_DAILY_UPDATE_AT, moment)
    db_session.commit()

    loaded = repo.get_datetime(KEY_LAST_DAILY_UPDATE_AT)
    assert loaded == moment
    assert loaded is not None and loaded.tzinfo is not None


def test_set_datetime_naive_gets_utc_tag(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    naive = datetime(2026, 1, 1, 0, 0, 0)
    repo.set_datetime(KEY_LAST_VACUUM_AT, naive)
    db_session.commit()

    loaded = repo.get_datetime(KEY_LAST_VACUUM_AT)
    assert loaded == naive.replace(tzinfo=UTC)


def test_get_datetime_parses_non_utc_offset(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    offset_tz = timezone(timedelta(hours=-4))
    when = datetime(2026, 4, 19, 6, 30, tzinfo=offset_tz)
    repo.set_datetime(KEY_LAST_DAILY_UPDATE_AT, when)
    db_session.commit()

    loaded = repo.get_datetime(KEY_LAST_DAILY_UPDATE_AT)
    assert loaded is not None
    assert loaded == when
    assert loaded.utcoffset() == timedelta(hours=-4)


def test_get_datetime_returns_none_for_garbage_value(db_session: Session) -> None:
    repo = SystemMetadataRepository(db_session)
    repo.set(KEY_LAST_BACKUP_AT, "not a datetime")
    db_session.commit()

    assert repo.get_datetime(KEY_LAST_BACKUP_AT) is None

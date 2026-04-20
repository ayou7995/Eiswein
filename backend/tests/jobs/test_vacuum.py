"""Tests for :mod:`app.jobs.vacuum`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.database import apply_sqlite_pragmas
from app.db.models import Base
from app.db.repositories.system_metadata_repository import (
    KEY_LAST_VACUUM_AT,
    SystemMetadataRepository,
)
from app.jobs import vacuum as vacuum_job


def _file_engine(path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    event.listen(engine, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(engine)
    return engine


@pytest.mark.asyncio
async def test_first_run_proceeds_and_records_metadata(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path / "db.sqlite")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    ran = await vacuum_job.run(engine=engine, session_factory=factory)
    assert ran is True

    with factory() as session:
        last = SystemMetadataRepository(session).get_datetime(KEY_LAST_VACUUM_AT)
    assert last is not None
    engine.dispose()


@pytest.mark.asyncio
async def test_second_run_within_cooldown_is_skipped(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path / "db.sqlite")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    first = await vacuum_job.run(engine=engine, session_factory=factory)
    assert first is True

    second = await vacuum_job.run(engine=engine, session_factory=factory)
    assert second is False
    engine.dispose()


@pytest.mark.asyncio
async def test_second_run_beyond_cooldown_runs(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path / "db.sqlite")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Manually pre-write a VERY stale "last_vacuum_at".
    with factory() as session:
        SystemMetadataRepository(session).set_datetime(
            KEY_LAST_VACUUM_AT, datetime(2020, 1, 1, tzinfo=UTC)
        )
        session.commit()

    ran = await vacuum_job.run(engine=engine, session_factory=factory, cooldown=timedelta(days=1))
    assert ran is True
    engine.dispose()


@pytest.mark.asyncio
async def test_cooldown_honors_injected_value(tmp_path: Path) -> None:
    engine = _file_engine(tmp_path / "db.sqlite")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as session:
        SystemMetadataRepository(session).set_datetime(
            KEY_LAST_VACUUM_AT, datetime.now(UTC) - timedelta(hours=1)
        )
        session.commit()

    # 2-hour cooldown, last was 1 hour ago → must skip.
    ran = await vacuum_job.run(engine=engine, session_factory=factory, cooldown=timedelta(hours=2))
    assert ran is False
    engine.dispose()


@pytest.mark.asyncio
async def test_vacuum_failure_is_logged_and_returns_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _file_engine(tmp_path / "db.sqlite")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    class ExplodingEngine:
        def begin(self) -> object:
            raise RuntimeError("vacuum-broken")

        @property
        def url(self) -> object:
            return engine.url

    ran = await vacuum_job.run(
        engine=ExplodingEngine(),  # type: ignore[arg-type]
        session_factory=factory,
    )
    assert ran is False
    engine.dispose()

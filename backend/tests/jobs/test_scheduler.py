"""Tests for :mod:`app.jobs.scheduler`.

The scheduler relies on ``fcntl.flock`` to prevent double-starts. The
test uses a real lock file in ``tmp_path`` so the exclusive-lock
behavior is verified end-to-end (no mocks around the OS primitive).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.database import apply_sqlite_pragmas
from app.db.models import Base
from app.jobs import scheduler as scheduler_module
from app.jobs.scheduler import get_scheduler_status, start_scheduler


@pytest.fixture
def file_engine(tmp_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'db.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    event.listen(engine, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def file_session_factory(file_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=file_engine, autoflush=False, expire_on_commit=False)


@pytest.mark.asyncio
async def test_start_scheduler_registers_all_four_jobs(
    settings: Settings,
    file_engine: Engine,
    file_session_factory: sessionmaker[Session],
    tmp_path: Path,
    fake_data_source: object,
) -> None:
    handle = start_scheduler(
        settings=settings,
        engine=file_engine,
        session_factory=file_session_factory,
        data_source=fake_data_source,  # type: ignore[arg-type]
        lock_path=tmp_path / "scheduler.lock",
    )
    assert handle is not None
    try:
        status = handle.status()
        assert status.status == "running"
        job_ids = sorted(job.id for job in status.jobs)
        assert job_ids == ["backup", "daily_update", "token_reminder", "vacuum"]
        # Every job must have a next_run_time set.
        assert all(job.next_run_time is not None for job in status.jobs)
    finally:
        handle.shutdown(wait=False)


@pytest.mark.asyncio
async def test_second_start_with_lock_held_returns_none(
    settings: Settings,
    file_engine: Engine,
    file_session_factory: sessionmaker[Session],
    tmp_path: Path,
    fake_data_source: object,
) -> None:
    lock_path = tmp_path / "scheduler.lock"
    handle_a = start_scheduler(
        settings=settings,
        engine=file_engine,
        session_factory=file_session_factory,
        data_source=fake_data_source,  # type: ignore[arg-type]
        lock_path=lock_path,
    )
    assert handle_a is not None
    try:
        handle_b = start_scheduler(
            settings=settings,
            engine=file_engine,
            session_factory=file_session_factory,
            data_source=fake_data_source,  # type: ignore[arg-type]
            lock_path=lock_path,
        )
        assert handle_b is None
    finally:
        handle_a.shutdown(wait=False)


@pytest.mark.asyncio
async def test_shutdown_releases_lock_for_next_start(
    settings: Settings,
    file_engine: Engine,
    file_session_factory: sessionmaker[Session],
    tmp_path: Path,
    fake_data_source: object,
) -> None:
    lock_path = tmp_path / "scheduler.lock"
    handle_a = start_scheduler(
        settings=settings,
        engine=file_engine,
        session_factory=file_session_factory,
        data_source=fake_data_source,  # type: ignore[arg-type]
        lock_path=lock_path,
    )
    assert handle_a is not None
    handle_a.shutdown(wait=False)

    handle_b = start_scheduler(
        settings=settings,
        engine=file_engine,
        session_factory=file_session_factory,
        data_source=fake_data_source,  # type: ignore[arg-type]
        lock_path=lock_path,
    )
    assert handle_b is not None
    handle_b.shutdown(wait=False)


def test_get_scheduler_status_with_none_handle() -> None:
    status = get_scheduler_status(None)
    assert status.status == "not_started"
    assert status.jobs == []


@pytest.mark.asyncio
async def test_status_error_branch(
    settings: Settings,
    file_engine: Engine,
    file_session_factory: sessionmaker[Session],
    tmp_path: Path,
    fake_data_source: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = start_scheduler(
        settings=settings,
        engine=file_engine,
        session_factory=file_session_factory,
        data_source=fake_data_source,  # type: ignore[arg-type]
        lock_path=tmp_path / "scheduler.lock",
    )
    assert handle is not None
    try:

        def broken(self: object) -> object:
            raise RuntimeError("status failure")

        monkeypatch.setattr(scheduler_module.SchedulerHandle, "status", broken)
        status = get_scheduler_status(handle)
        assert status.status == "error"
    finally:
        handle.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scheduler_wrappers_are_async_coroutines() -> None:
    # Sanity — job function references must be coroutines the scheduler
    # can await. If someone redefines one as a sync function by
    # accident, the scheduler would silently swallow the return value.
    import inspect

    for wrapper in (
        scheduler_module._daily_update_wrapper,
        scheduler_module._backup_wrapper,
        scheduler_module._token_reminder_wrapper,
        scheduler_module._vacuum_wrapper,
    ):
        assert inspect.iscoroutinefunction(wrapper)

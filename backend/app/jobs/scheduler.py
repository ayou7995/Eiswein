"""APScheduler wiring with fcntl lock guard (Phase 6).

Hard operational invariants this module upholds
-----------------------------------------------
* ``uvicorn --workers 1`` is enforced in docker-compose; this module
  adds a belt-and-suspenders ``fcntl.flock(LOCK_EX | LOCK_NB)`` on a
  lock file so that even if the deploy drifts, only one scheduler
  instance runs.
* ``AsyncIOScheduler`` runs inside FastAPI's asyncio loop — jobs can
  be ``async def`` and they share DB connections with the request
  loop.
* Each job gets a stable ID so ``get_scheduler_status`` surfaces it
  reliably to the health endpoint and so the scheduler's
  replace-existing upsert semantics are deterministic.

Nothing here catches broad exceptions around ``start()`` itself —
if APScheduler fails to start, that's a configuration bug the
operator needs to see; the FastAPI ``lifespan`` wraps the call so a
scheduler failure doesn't block request serving.
"""

from __future__ import annotations

import contextlib
import fcntl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.datasources.base import DataSource
from app.jobs import backup as backup_job
from app.jobs import daily_update as daily_update_job
from app.jobs import token_reminder as token_reminder_job
from app.jobs import vacuum as vacuum_job

logger = structlog.get_logger("eiswein.jobs.scheduler")

_DEFAULT_LOCK_PATH = Path("data/scheduler.lock")
_TIMEZONE = "America/New_York"


JobId = Literal["daily_update", "backup", "token_reminder", "vacuum"]


@dataclass(frozen=True)
class JobInfo:
    id: str
    next_run_time: datetime | None


@dataclass(frozen=True)
class SchedulerStatus:
    status: Literal["running", "not_started", "error"]
    jobs: list[JobInfo]


class SchedulerHandle:
    """Runtime handle for the started scheduler + lock.

    Stored on ``app.state.scheduler_handle`` so the lifespan shutdown
    can release both cleanly. Never instantiated outside this
    module — use :func:`start_scheduler`.
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        lock_fd: IO[bytes],
        lock_path: Path,
    ) -> None:
        self._scheduler = scheduler
        self._lock_fd = lock_fd
        self._lock_path = lock_path

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def status(self) -> SchedulerStatus:
        if not self._scheduler.running:
            return SchedulerStatus(status="not_started", jobs=[])
        jobs = [
            JobInfo(id=job.id, next_run_time=job.next_run_time)
            for job in self._scheduler.get_jobs()
        ]
        return SchedulerStatus(status="running", jobs=jobs)

    def shutdown(self, *, wait: bool = True) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=wait)
        finally:
            _release_lock(self._lock_fd)
            logger.info("scheduler_stopped", lock_path=str(self._lock_path))


def start_scheduler(
    *,
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    data_source: DataSource,
    lock_path: Path = _DEFAULT_LOCK_PATH,
) -> SchedulerHandle | None:
    """Start the APScheduler, registering every Phase 6 job.

    Returns ``None`` without raising if the lock file is already held
    by a sibling process. Any other failure (bad cron spec, missing
    event loop) propagates so the caller can surface it.
    """
    lock_fd = _try_acquire_lock(lock_path)
    if lock_fd is None:
        logger.warning(
            "scheduler_lock_not_acquired",
            lock_path=str(lock_path),
            note="another process holds the lock; scheduler not started",
        )
        return None

    scheduler = AsyncIOScheduler(timezone=_TIMEZONE)
    _register_jobs(
        scheduler=scheduler,
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        data_source=data_source,
    )
    scheduler.start()
    logger.info(
        "scheduler_started",
        lock_path=str(lock_path),
        timezone=_TIMEZONE,
        jobs=[job.id for job in scheduler.get_jobs()],
    )
    return SchedulerHandle(scheduler, lock_fd, lock_path)


def _try_acquire_lock(lock_path: Path) -> IO[bytes] | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Use binary mode so the IO[bytes] type matches cleanly, and so we
    # aren't at the mercy of locale-encoded text streams for what
    # should be a simple flock target.
    fd: IO[bytes] = open(lock_path, "ab+")  # noqa: SIM115 — fd must outlive this function
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        return None
    except OSError:
        fd.close()
        raise
    return fd


def _release_lock(fd: IO[bytes]) -> None:
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("scheduler_lock_release_failed", error=str(exc))
    finally:
        with contextlib.suppress(OSError):
            fd.close()


def _register_jobs(
    *,
    scheduler: AsyncIOScheduler,
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    data_source: DataSource,
) -> None:
    backup_dir = Path(settings.database_url.removeprefix("sqlite:///")).parent / "backups"

    scheduler.add_job(
        _daily_update_wrapper,
        trigger=CronTrigger(hour=6, minute=30, day_of_week="*", timezone=_TIMEZONE),
        id="daily_update",
        name="daily_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        kwargs={
            "session_factory": session_factory,
            "data_source": data_source,
            "settings": settings,
        },
    )
    scheduler.add_job(
        _backup_wrapper,
        trigger=CronTrigger(hour=7, minute=0, timezone=_TIMEZONE),
        id="backup",
        name="backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        kwargs={
            "source_engine": engine,
            "backup_dir": backup_dir,
            "session_factory": session_factory,
        },
    )
    scheduler.add_job(
        _token_reminder_wrapper,
        trigger=CronTrigger(hour=9, minute=15, timezone=_TIMEZONE),
        id="token_reminder",
        name="token_reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        kwargs={
            "session_factory": session_factory,
            "settings": settings,
        },
    )
    scheduler.add_job(
        _vacuum_wrapper,
        trigger=CronTrigger(day="1-7", day_of_week="sun", hour=3, minute=0, timezone=_TIMEZONE),
        id="vacuum",
        name="vacuum",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        kwargs={
            "engine": engine,
            "session_factory": session_factory,
        },
    )


# --- apscheduler entry points --------------------------------------------
# APScheduler serializes the `func` target to its import path when the
# job store is persistent. We use the default in-memory store so that's
# not strictly required — the wrappers exist mainly to normalise the
# call signatures and give a single place to hang additional
# observability later.


async def _daily_update_wrapper(**kwargs: Any) -> None:
    await daily_update_job.run(**kwargs)


async def _backup_wrapper(**kwargs: Any) -> None:
    await backup_job.run(**kwargs)


async def _token_reminder_wrapper(**kwargs: Any) -> None:
    await token_reminder_job.run(**kwargs)


async def _vacuum_wrapper(**kwargs: Any) -> None:
    await vacuum_job.run(**kwargs)


def get_scheduler_status(handle: SchedulerHandle | None) -> SchedulerStatus:
    """Shape the scheduler state for the health endpoint.

    Treating ``None`` as "not_started" (not "error") means that
    skipping scheduler startup during tests or local dev does not
    degrade the health response to an error-level state.
    """
    if handle is None:
        return SchedulerStatus(status="not_started", jobs=[])
    try:
        return handle.status()
    except Exception as exc:
        logger.warning(
            "scheduler_status_raised",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return SchedulerStatus(status="error", jobs=[])

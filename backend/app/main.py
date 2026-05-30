"""FastAPI application factory.

Composition root
----------------
`create_app()` wires every infrastructure concern into `app.state` so
dependency-injected handlers stay free of module-level globals (rule 13).

Startup order (lifespan context)
--------------------------------
1. Configure structlog with sensitive-key redaction.
2. Build SQLite engine (WAL mode via event listener).
3. Validate schema exists (Alembic already ran via entrypoint — here we
   just ensure the metadata tables are importable).
4. Seed admin user from ADMIN_USERNAME + ADMIN_PASSWORD_HASH on first
   boot. Refuse to start if either is missing (A3).
5. Mount middleware + routers.

Shutdown
--------
* Dispose DB engine (I24). Scheduler shutdown hooks in Phase 6.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import build_v1_router
from app.config import Settings, get_settings
from app.datasources.base import DataSource
from app.datasources.factory import build_data_source
from app.db.database import build_session_factory, create_db_engine
from app.db.repositories.user_repository import UserRepository
from app.ingestion.daily_ingestion import run_daily_update
from app.jobs.scheduler import SchedulerHandle, start_scheduler
from app.security.error_handlers import register_error_handlers
from app.security.exceptions import EisweinError
from app.security.logging import configure_logging
from app.security.middleware import (
    ClientIPMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.security.rate_limit import limiter as app_limiter
from app.services.backfill_service import mark_orphaned_backfills_failed


def _seed_admin_if_needed(settings: Settings, users: UserRepository) -> None:
    """First-boot seed: write the .env ADMIN_PASSWORD_HASH into the
    users table when the table is empty. After that, the DB is the
    source of truth — the in-app password-change endpoint and
    scripts/reset_password_offline.py both write to the DB, NOT to
    .env. Re-running ``make install`` overwrites ``.env`` but does not
    touch the DB; the operator must wipe ``data/eiswein.db`` (or use
    the offline reset script) to pick up a new install-time hash.

    Logs the skip path loudly so anyone tailing ``make logs`` after a
    failed login can see "the admin already exists, your fresh .env
    hash was ignored" instead of staring at a silent boot.
    """
    structlog_logger = structlog.get_logger("eiswein.lifespan")
    if users.count() > 0:
        structlog_logger.info(
            "admin_seed_skipped_user_exists",
            note=(
                "DB already has an admin row — .env ADMIN_PASSWORD_HASH "
                "was NOT applied. To reset password: stop container, "
                "rm -rf data/, restart; OR run scripts/"
                "reset_password_offline.py."
            ),
        )
        return
    users.create(
        username=settings.admin_username,
        password_hash=settings.admin_password_hash.get_secret_value(),
        is_admin=True,
    )
    structlog_logger.info(
        "admin_seeded",
        username=settings.admin_username,
    )


async def _startup_catchup_daily_update(
    *,
    session_factory: sessionmaker[Session],
    data_source: DataSource,
    settings: Settings,
) -> None:
    """Fire one daily_update fire-and-forget after the app starts.

    Handles the laptop-sleep scenario: APScheduler's cron trigger fires
    at 06:30 ET, but if the host was asleep at that moment the misfire
    grace period (1 hour) closes long before the user comes back. On
    next process boot we kick off a single ``run_daily_update`` to fill
    whatever gaps accumulated. ``run_daily_update`` already short-
    circuits when the watchlist has no gaps for the session day, so
    this is a no-op on a fresh same-day restart.

    Runs as a background task so the HTTP server starts accepting
    requests immediately. Errors are logged but never propagated —
    catch-up is a convenience, not a startup precondition.
    """
    logger = structlog.get_logger("eiswein.startup_catchup")
    try:
        with session_factory() as session:
            result = await run_daily_update(
                db=session,
                data_source=data_source,
                settings=settings,
                # ``startup`` (vs ``scheduled``) tells daily_update this
                # is a boot-time catch-up — the catalyst-digest email
                # is suppressed. Without this gate, every container
                # restart / make-dev reload would send another email.
                trigger="startup",
            )
            session.commit()
        logger.info(
            "startup_catchup_complete",
            market_open=result.market_open,
            gaps_filled_symbols=result.gaps_filled_symbols,
            gaps_filled_rows=result.gaps_filled_rows,
            price_rows_upserted=result.price_rows_upserted,
        )
    except Exception as exc:
        logger.warning(
            "startup_catchup_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    logger = structlog.get_logger("eiswein.lifespan")

    preinjected_engine = getattr(app.state, "engine", None)
    preinjected_factory = getattr(app.state, "session_factory", None)
    engine: Engine
    session_factory: sessionmaker[Session]
    if preinjected_engine is None or preinjected_factory is None:
        engine = create_db_engine(settings)
        session_factory = build_session_factory(engine)
        app.state.engine = engine
        app.state.session_factory = session_factory
        owns_engine = True
    else:
        engine = preinjected_engine
        session_factory = preinjected_factory
        owns_engine = False

    with session_factory() as session:
        try:
            _seed_admin_if_needed(settings, UserRepository(session))
            # Reap any backfill_job rows left in pending/running by a
            # prior crash. Running this inside the admin-seed session
            # keeps startup to a single commit.
            mark_orphaned_backfills_failed(session=session)
            session.commit()
        except EisweinError:
            session.rollback()
            raise

    scheduler_handle: SchedulerHandle | None = None
    preinjected_handle = getattr(app.state, "scheduler_handle", None)
    # Tests set ``scheduler_disabled=True`` on app.state to skip Phase 6
    # startup entirely (the TestClient runs hundreds of lifespan cycles
    # and each fcntl.flock acquire/release would churn a shared lock
    # file). Production + dev always get the scheduler.
    if preinjected_handle is not None:
        scheduler_handle = preinjected_handle
    elif not getattr(app.state, "scheduler_disabled", False):
        try:
            data_source = getattr(app.state, "data_source", None)
            if data_source is None:
                data_source = build_data_source(settings)
                app.state.data_source = data_source
            scheduler_handle = start_scheduler(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                data_source=data_source,
            )
        except Exception as exc:
            # Scheduler start failure must not block the API from
            # serving requests — log + continue so the operator can
            # still hit /health and diagnose.
            logger.warning(
                "scheduler_start_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            scheduler_handle = None
    app.state.scheduler_handle = scheduler_handle

    # Fire-and-forget catch-up on every startup IF the scheduler is
    # running (production + dev). The same ``scheduler_disabled`` gate
    # that disables APScheduler also implicitly disables the catch-up
    # — tests run hundreds of lifespan cycles and each fire would
    # churn cache + DB locks for no benefit. Suppressible via the new
    # ``startup_catchup_disabled`` flag for the rare test that needs
    # scheduler but not catch-up.
    catchup_task: asyncio.Task[None] | None = None
    if scheduler_handle is not None and not getattr(app.state, "startup_catchup_disabled", False):
        data_source_for_catchup = getattr(app.state, "data_source", None)
        if data_source_for_catchup is not None:
            catchup_task = asyncio.create_task(
                _startup_catchup_daily_update(
                    session_factory=session_factory,
                    data_source=data_source_for_catchup,
                    settings=settings,
                )
            )
    app.state.startup_catchup_task = catchup_task

    logger.info(
        "app_started",
        environment=settings.environment,
        db=str(engine.url).split("@")[-1],
        scheduler="running" if scheduler_handle is not None else "not_started",
        startup_catchup="scheduled" if catchup_task is not None else "skipped",
    )

    try:
        yield
    finally:
        logger.info("app_stopping")
        # Cancel the startup catch-up task if it hasn't finished —
        # better to abort a half-finished fetch than to block uvicorn
        # shutdown waiting for a multi-minute job.
        active_catchup: asyncio.Task[None] | None = getattr(app.state, "startup_catchup_task", None)
        if active_catchup is not None and not active_catchup.done():
            active_catchup.cancel()
            try:
                await active_catchup
            except asyncio.CancelledError:
                # Expected — we just cancelled it. Swallow so cleanup continues.
                pass
            except Exception as exc:
                logger.warning(
                    "startup_catchup_cancel_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
        handle: SchedulerHandle | None = app.state.scheduler_handle
        if handle is not None:
            try:
                handle.shutdown(wait=True)
            except Exception as exc:
                logger.warning(
                    "scheduler_shutdown_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
        if owns_engine:
            engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """ASGI factory — invoked via `uvicorn app.main:create_app --factory`.

    Tests import this directly and pass in a test ``Settings`` instance;
    production invocation resolves settings from env vars. No module-level
    ``app`` singleton exists: importing this module has no side effects,
    so tests never need a bootstrap escape hatch.
    """
    resolved = settings or get_settings()

    is_production = resolved.environment == "production"

    app = FastAPI(
        title="Eiswein API",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url=None if is_production else "/api/v1/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/api/v1/openapi.json",
    )
    app.state.settings = resolved
    app.state.limiter = app_limiter

    # Middleware add order is reverse execution order — last added runs first.
    # ClientIP must run before rate limiter so that the limiter keys off the
    # validated CF-Connecting-IP, not the transport peer.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(ClientIPMiddleware, extra_trusted=tuple(resolved.trusted_proxies))
    app.add_middleware(RequestContextMiddleware)

    # Our rate_limit_exceeded_handler (registered inside register_error_handlers)
    # replaces slowapi's default so 429 responses use the project's
    # standardized error envelope instead of slowapi's plain-text body.
    register_error_handlers(app)

    app.include_router(build_v1_router())

    # Serve the built React bundle when present (production /
    # distributable Docker image). The Dockerfile copies the Vite
    # output to /app/frontend_dist; ``StaticFiles(html=True)`` falls
    # back to index.html for any path that isn't a real file, so the
    # client-side router handles deep links like /ticker/SPY. Mount
    # order matters: API routes registered above take precedence,
    # this catch-all only fires on non-API paths.
    _mount_frontend_if_present(app)
    return app


def _mount_frontend_if_present(app: FastAPI) -> None:
    """Look for the Vite build output in the standard locations and
    mount it at ``/``. No-op when the directory is missing — the same
    factory powers ``make dev`` (Vite serves the frontend separately
    on :5173 in that case)."""
    candidates = (
        Path("/app/frontend_dist"),
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
    for path in candidates:
        if path.is_dir() and (path / "index.html").is_file():
            app.mount("/", StaticFiles(directory=str(path), html=True), name="frontend")
            return

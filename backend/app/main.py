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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import build_v1_router
from app.config import Settings, get_settings
from app.db.database import build_session_factory, create_db_engine
from app.db.repositories.user_repository import UserRepository
from app.security.error_handlers import register_error_handlers
from app.security.exceptions import EisweinError
from app.security.logging import configure_logging
from app.security.middleware import (
    ClientIPMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.security.rate_limit import limiter as app_limiter


def _seed_admin_if_needed(settings: Settings, users: UserRepository) -> None:
    if users.count() > 0:
        return
    users.create(
        username=settings.admin_username,
        password_hash=settings.admin_password_hash.get_secret_value(),
        is_admin=True,
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
            session.commit()
        except EisweinError:
            session.rollback()
            raise

    logger.info(
        "app_started",
        environment=settings.environment,
        db=str(engine.url).split("@")[-1],
    )

    try:
        yield
    finally:
        logger.info("app_stopping")
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
    return app

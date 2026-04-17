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

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
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
    resolved = settings or get_settings()

    app = FastAPI(
        title="Eiswein API",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/api/v1/docs" if resolved.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.settings = resolved

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ClientIPMiddleware, extra_trusted=tuple(resolved.trusted_proxies))
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    app.include_router(build_v1_router())
    return app


def _make_module_app() -> FastAPI:
    """uvicorn entrypoint: `uvicorn app.main:app`.

    Boot-time failures (missing ADMIN_PASSWORD_HASH, weak JWT secret,
    etc.) MUST surface to the operator, so we let the exception from
    `Settings()` propagate. Set EISWEIN_SKIP_BOOTSTRAP=1 in environments
    (tests, docs generation) that import this module but won't serve.
    """
    if os.environ.get("EISWEIN_SKIP_BOOTSTRAP") == "1":
        return FastAPI(title="Eiswein API (bootstrap skipped)")
    return create_app()


app: FastAPI = _make_module_app()

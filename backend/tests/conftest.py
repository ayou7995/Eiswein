"""Shared pytest fixtures — test settings, in-memory DB, FastAPI client."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.database import apply_sqlite_pragmas
from app.db.models import Base
from app.main import create_app


@pytest.fixture(scope="session")
def test_password() -> str:
    return "correcthorsebatterystaple-testing"


@pytest.fixture(scope="session")
def admin_password_hash(test_password: str) -> str:
    return bcrypt.hashpw(test_password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")


@pytest.fixture(scope="session")
def encryption_key_b64() -> str:
    raw = os.urandom(32)
    return base64.urlsafe_b64encode(raw).decode("utf-8")


@pytest.fixture
def settings(admin_password_hash: str, encryption_key_b64: str) -> Settings:
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="test" * 20,  # noqa: S106 — test fixture
        encryption_key=encryption_key_b64,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash=admin_password_hash,  # type: ignore[arg-type]
        cookie_secure=False,
        login_lockout_threshold=3,
        login_lockout_minutes=15,
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
        future=True,
    )
    event.listen(eng, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def app(settings: Settings, engine: Engine, session_factory: sessionmaker[Session]) -> FastAPI:
    application = create_app(settings)
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    return application


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    """Reset slowapi in-memory storage between tests so rate limits don't
    accumulate across test functions sharing the same TestClient IP."""
    from app.security.rate_limit import limiter as module_limiter

    module_limiter.reset()
    yield
    module_limiter.reset()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as tc:
        yield tc

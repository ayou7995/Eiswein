"""Shared pytest fixtures — test settings, in-memory DB, FastAPI client."""

from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.datasources.base import DataSource, DataSourceHealth
from app.db.database import apply_sqlite_pragmas
from app.db.models import Base
from app.main import create_app
from app.security.exceptions import DataSourceError


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
def settings(
    admin_password_hash: str,
    encryption_key_b64: str,
    tmp_path: Path,
) -> Settings:
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="test" * 20,
        encryption_key=encryption_key_b64,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash=admin_password_hash,  # type: ignore[arg-type]
        cookie_secure=False,
        login_lockout_threshold=3,
        login_lockout_minutes=15,
        cache_dir=tmp_path / "cache",
        watchlist_max_size=5,  # small so B3 cap test is fast
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


def _make_price_frame(
    days: int = 60,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Deterministic OHLCV frame — shared across ingestion + API tests."""
    origin = datetime(2026, 1, 2, tzinfo=UTC)
    idx = pd.date_range(origin, periods=days, freq="B", tz="America/New_York")
    rng = np.random.default_rng(seed=42)
    base = start_price + np.cumsum(rng.normal(0, 1.0, size=days))
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + 0.5,
            "volume": rng.integers(1_000_000, 5_000_000, size=days).astype(np.int64),
        },
        index=idx,
    )


@dataclass
class FakeDataSourceConfig:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    empty_for: set[str] = field(default_factory=set)
    error_for: set[str] = field(default_factory=set)
    delay_seconds: float = 0.0
    health: DataSourceHealth = field(
        default_factory=lambda: DataSourceHealth(status="ok")
    )


class FakeDataSource(DataSource):
    def __init__(self, config: FakeDataSourceConfig | None = None) -> None:
        self.config = config or FakeDataSourceConfig()
        self.calls: list[tuple[str, list[str], str]] = []

    @property
    def name(self) -> str:
        return "fake"

    async def bulk_download(
        self, symbols: list[str], *, period: str = "2y"
    ) -> dict[str, pd.DataFrame]:
        self.calls.append(("bulk", list(symbols), period))
        if self.config.delay_seconds > 0:
            await asyncio.sleep(self.config.delay_seconds)
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            upper = sym.upper()
            if upper in self.config.error_for:
                raise DataSourceError(
                    details={"reason": "upstream_error", "symbol": upper}
                )
            if upper in self.config.empty_for:
                out[upper] = pd.DataFrame()
                continue
            out[upper] = self.config.frames.get(upper, _make_price_frame())
        return out

    async def get_index_data(
        self, symbol: str, *, period: str = "2y"
    ) -> pd.DataFrame:
        result = await self.bulk_download([symbol], period=period)
        frame = result.get(symbol.upper())
        if frame is None or frame.empty:
            raise DataSourceError(
                details={"reason": "delisted_or_invalid", "symbol": symbol}
            )
        return frame

    async def health_check(self) -> DataSourceHealth:
        return self.config.health


@pytest.fixture
def fake_data_source() -> FakeDataSource:
    return FakeDataSource()


@pytest.fixture
def make_price_frame() -> Callable[..., pd.DataFrame]:
    return _make_price_frame


@pytest.fixture(autouse=True)
def _reset_ingestion_locks() -> Iterator[None]:
    from app.ingestion.locks import reset_locks_for_tests

    reset_locks_for_tests()
    yield
    reset_locks_for_tests()


@pytest.fixture
def app(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
) -> FastAPI:
    application = create_app(settings)
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.data_source = fake_data_source
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

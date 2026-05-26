"""FastAPI dependency providers — the composition root entry points.

All runtime wiring (session factory, repositories, settings) is attached
to `app.state` at startup (see main.py) and exposed to routes through
these `Depends(...)` shims. This keeps the API layer testable (override
dependencies) and free of module-level globals (rule 13).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.datasources.base import DataSource
from app.datasources.factory import build_data_source
from app.db.repositories.audit_repository import AuditRepository
from app.db.repositories.broker_credential_repository import BrokerCredentialRepository
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.daily_signal_repository import DailySignalRepository
from app.db.repositories.macro_repository import MacroRepository
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.db.repositories.market_snapshot_repository import MarketSnapshotRepository
from app.db.repositories.ticker_repository import TickerRepository
from app.db.repositories.ticker_snapshot_repository import TickerSnapshotRepository
from app.db.repositories.user_repository import UserRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.security.auth import decode_token
from app.security.exceptions import AuthError, EisweinError, TokenInvalidError

COOKIE_ACCESS = "eiswein_access"
COOKIE_REFRESH = "eiswein_refresh"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_db_session(request: Request) -> Iterator[Session]:
    factory = _session_factory(request)
    session = factory()
    try:
        yield session
    except EisweinError:
        # Domain errors (invalid password, locked out, etc.) are expected
        # outcomes, not programming bugs. The audit log rows written during
        # the failed request MUST be persisted so subsequent requests can
        # see the failure history (e.g., IP-based lockout).
        session.commit()
        raise
    except Exception:
        session.rollback()
        raise
    else:
        session.commit()
    finally:
        session.close()


def get_user_repository(session: Session = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)


def get_audit_repository(session: Session = Depends(get_db_session)) -> AuditRepository:
    return AuditRepository(session)


def get_ticker_repository(session: Session = Depends(get_db_session)) -> TickerRepository:
    return TickerRepository(session)


def get_broker_credential_repository(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> BrokerCredentialRepository:
    return BrokerCredentialRepository(session, settings.encryption_key_bytes())


def get_watchlist_repository(
    session: Session = Depends(get_db_session),
) -> WatchlistRepository:
    return WatchlistRepository(session)


def get_daily_price_repository(
    session: Session = Depends(get_db_session),
) -> DailyPriceRepository:
    return DailyPriceRepository(session)


def get_macro_repository(
    session: Session = Depends(get_db_session),
) -> MacroRepository:
    return MacroRepository(session)


def get_daily_signal_repository(
    session: Session = Depends(get_db_session),
) -> DailySignalRepository:
    return DailySignalRepository(session)


def get_ticker_snapshot_repository(
    session: Session = Depends(get_db_session),
) -> TickerSnapshotRepository:
    return TickerSnapshotRepository(session)


def get_market_snapshot_repository(
    session: Session = Depends(get_db_session),
) -> MarketSnapshotRepository:
    return MarketSnapshotRepository(session)


def get_market_posture_streak_repository(
    session: Session = Depends(get_db_session),
) -> MarketPostureStreakRepository:
    return MarketPostureStreakRepository(session)


def get_data_source_dep(request: Request) -> DataSource:
    """Resolve the active :class:`DataSource`.

    Cached on ``app.state`` to keep the parquet cache directory
    initialization to once per process; tests can override the
    dependency to inject a :class:`FakeDataSource` without touching
    any real provider.
    """
    cached = getattr(request.app.state, "data_source", None)
    if cached is not None:
        assert isinstance(cached, DataSource)
        return cached
    settings: Settings = request.app.state.settings
    source = build_data_source(settings)
    request.app.state.data_source = source
    return source


def current_user_id(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> int:
    token = request.cookies.get(COOKIE_ACCESS)
    if not token:
        raise AuthError()
    payload = decode_token(
        token,
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        expected_type="access",
    )
    try:
        return int(payload.subject)
    except ValueError as exc:
        raise TokenInvalidError("invalid subject") from exc

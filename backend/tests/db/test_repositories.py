"""Repository CRUD roundtrips."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.audit_repository import (
    LOGIN_FAILURE,
    LOGIN_SUCCESS,
    AuditRepository,
)
from app.db.repositories.broker_credential_repository import BrokerCredentialRepository
from app.db.repositories.ticker_repository import TickerRepository
from app.db.repositories.user_repository import UserRepository


def test_user_create_and_lookup(db_session: Session) -> None:
    repo = UserRepository(db_session)
    user = repo.create(username="alice", password_hash="$2b$12$x", is_admin=True)
    db_session.commit()

    assert repo.count() == 1
    fetched = repo.by_username("alice")
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.is_admin is True


def test_audit_record_and_fetch_recent(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    repo.record(LOGIN_SUCCESS, ip="1.1.1.1")
    repo.record(LOGIN_FAILURE, ip="1.1.1.1")
    db_session.commit()

    attempts = repo.recent_login_attempts(window=timedelta(hours=1))
    assert len(attempts) == 2
    # Sorted desc by timestamp; the LOGIN_FAILURE was recorded after SUCCESS.
    assert attempts[0].success is False
    assert attempts[1].success is True


def test_ticker_upsert_is_idempotent(db_session: Session) -> None:
    repo = TickerRepository(db_session)
    first = repo.upsert(symbol="spy", name="SPDR S&P 500")
    second = repo.upsert(symbol="SPY", name="SPDR S&P 500")
    db_session.commit()
    assert first.id == second.id
    assert first.symbol == "SPY"


def test_broker_credential_store_and_load(db_session: Session) -> None:
    import os

    key = os.urandom(32)
    user_repo = UserRepository(db_session)
    user = user_repo.create(username="bob", password_hash="$2b$12$h")
    db_session.commit()

    cred_repo = BrokerCredentialRepository(db_session, key)
    cred_repo.store_refresh_token(
        user_id=user.id,
        broker="schwab",
        refresh_token="super-secret-refresh",
    )
    db_session.commit()

    plaintext = cred_repo.load_refresh_token(user_id=user.id, broker="schwab")
    assert plaintext == "super-secret-refresh"


def test_broker_credential_unique_per_user_broker(db_session: Session) -> None:
    import os

    key = os.urandom(32)
    user_repo = UserRepository(db_session)
    user = user_repo.create(username="carol", password_hash="$2b$12$h")
    db_session.commit()

    cred_repo = BrokerCredentialRepository(db_session, key)
    cred_repo.store_refresh_token(user_id=user.id, broker="schwab", refresh_token="t1")
    # Second store for same (user, broker) overwrites, not inserts.
    cred_repo.store_refresh_token(user_id=user.id, broker="schwab", refresh_token="t2")
    db_session.commit()

    assert cred_repo.load_refresh_token(user_id=user.id, broker="schwab") == "t2"


def test_broker_credential_load_missing_returns_none(db_session: Session) -> None:
    import os

    key = os.urandom(32)
    user_repo = UserRepository(db_session)
    user = user_repo.create(username="dave", password_hash="$2b$12$h")
    db_session.commit()

    cred_repo = BrokerCredentialRepository(db_session, key)
    assert cred_repo.load_refresh_token(user_id=user.id, broker="schwab") is None


@pytest.mark.parametrize("symbol", ["aapl", "MSFT", "BRK.B"])
def test_ticker_symbol_normalized_uppercase(db_session: Session, symbol: str) -> None:
    repo = TickerRepository(db_session)
    t = repo.upsert(symbol=symbol)
    db_session.commit()
    assert t.symbol == symbol.upper()

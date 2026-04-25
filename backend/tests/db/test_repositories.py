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


def test_broker_credential_delete_roundtrip(db_session: Session) -> None:
    import os

    key = os.urandom(32)
    user_repo = UserRepository(db_session)
    user = user_repo.create(username="eve", password_hash="$2b$12$h")
    db_session.commit()

    cred_repo = BrokerCredentialRepository(db_session, key)
    # Delete on absent row returns False (no-op, caller-friendly).
    assert cred_repo.delete(user_id=user.id, broker="schwab") is False

    cred_repo.store_refresh_token(user_id=user.id, broker="schwab", refresh_token="t1")
    db_session.commit()
    assert cred_repo.delete(user_id=user.id, broker="schwab") is True
    db_session.commit()
    assert cred_repo.load_refresh_token(user_id=user.id, broker="schwab") is None


# --- Schwab OAuth wire + scheduler smoke tests ----------------------------
# The full wire-level + route-level tests land in task #36; these just
# ensure the new modules import without regressions and that the
# ``schwab_enabled`` gate behaves as documented.


def test_schwab_oauth_module_importable() -> None:
    from app.datasources import schwab_oauth

    # Sanity: public symbols exist and error hierarchy is as documented.
    assert issubclass(schwab_oauth.SchwabOAuthError, Exception)
    assert issubclass(schwab_oauth.SchwabApiError, Exception)
    assert callable(schwab_oauth.exchange_code_for_tokens)
    assert callable(schwab_oauth.refresh_access_token)
    assert callable(schwab_oauth.get_user_preference)
    assert callable(schwab_oauth.get_account_numbers)


def test_schwab_session_module_importable() -> None:
    from app.services import schwab_session

    assert callable(schwab_session.get_or_refresh_access_token)
    assert callable(schwab_session.clear_cached_access_token)
    assert issubclass(schwab_session.SchwabReauthRequired, Exception)


def test_schwab_token_refresh_job_importable() -> None:
    from app.jobs import schwab_token_refresh

    assert schwab_token_refresh.JOB_NAME == "schwab_token_refresh"
    assert callable(schwab_token_refresh.run)


def test_schwab_enabled_defaults_false_without_secrets() -> None:
    """Config gate: no client id/secret ⇒ schwab_enabled is False."""
    import base64
    import os

    import bcrypt

    from app.config import Settings

    Settings.model_rebuild()  # pick up any pydantic cache
    pw_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode("utf-8")
    enc_key = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
    s = Settings(
        environment="development",
        jwt_secret="x" * 64,  # type: ignore[arg-type]
        encryption_key=enc_key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash=pw_hash,  # type: ignore[arg-type]
    )
    assert s.schwab_enabled is False
    assert s.schwab_client_id is None


def test_schwab_enabled_true_when_both_secrets_present() -> None:
    """Both id + secret set ⇒ schwab_enabled flips True."""
    import base64
    import os

    import bcrypt

    from app.config import Settings

    pw_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode("utf-8")
    enc_key = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
    s = Settings(
        environment="development",
        jwt_secret="x" * 64,  # type: ignore[arg-type]
        encryption_key=enc_key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash=pw_hash,  # type: ignore[arg-type]
        schwab_client_id="cid",  # type: ignore[arg-type]
        schwab_client_secret="csecret",  # type: ignore[arg-type]
    )
    assert s.schwab_enabled is True


def test_broker_routes_status_absent_returns_connected_false(client: object) -> None:
    """Unauthenticated status endpoint should 401; imports don't regress."""
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    resp = client.get("/api/v1/broker/schwab/status")
    # No auth cookie → 401 from current_user_id dependency. This covers
    # the "route is mounted" invariant without requiring a Schwab config.
    assert resp.status_code == 401


def test_broker_schwab_start_rejects_when_not_configured(
    client: object, test_password: str
) -> None:
    """`settings.schwab_enabled=False` ⇒ /start returns 400 schwab_not_configured."""
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    login = client.post("/api/v1/login", json={"username": "admin", "password": test_password})
    assert login.status_code == 200
    resp = client.get("/api/v1/broker/schwab/start", follow_redirects=False)
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "schwab_not_configured"


def test_broker_schwab_status_authenticated_returns_not_connected(
    client: object, test_password: str
) -> None:
    """Authenticated caller without a credential row sees ``connected=False``."""
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    login = client.post("/api/v1/login", json={"username": "admin", "password": test_password})
    assert login.status_code == 200
    resp = client.get("/api/v1/broker/schwab/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["accounts"] == []

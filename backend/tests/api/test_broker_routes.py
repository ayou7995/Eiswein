"""Broker routes tests — /api/v1/broker/schwab/* endpoints.

Authentication pattern: login as admin, which creates the session cookies that
all subsequent requests on the same TestClient will carry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, BrokerCredential, User
from app.security.encryption import encrypt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _seed_schwab_credential(
    session_factory: sessionmaker[Session],
    user_id: int,
    encryption_key: bytes,
    accounts: list[dict[str, Any]] | None = None,
) -> None:
    """Insert a fully-populated Schwab BrokerCredential (refresh token + metadata)."""

    if accounts is None:
        accounts = [
            {
                "plaintext_acct": "11223344",
                "hash_value": "hashed_abc",
                "display_id": "...3344",
                "nickname": "Brokerage",
            }
        ]

    rt_bundle = encrypt(b"stored_refresh_token", encryption_key)
    cust_bundle = encrypt(b"cust_001", encryption_key)
    correl_bundle = encrypt(b"correl_001", encryption_key)
    accounts_json = json.dumps(accounts, separators=(",", ":")).encode()
    accounts_bundle = encrypt(accounts_json, encryption_key)

    with session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
        if row is None:
            row = BrokerCredential(
                user_id=user_id,
                broker="schwab",
                encrypted_refresh_token=rt_bundle.ciphertext,
                token_nonce=rt_bundle.nonce,
                token_tag=rt_bundle.tag,
            )
            session.add(row)
            session.flush()
        # Attach metadata
        row.encrypted_streamer_customer_id = cust_bundle.ciphertext
        row.streamer_customer_id_nonce = cust_bundle.nonce
        row.streamer_customer_id_tag = cust_bundle.tag
        row.encrypted_streamer_correl_id = correl_bundle.ciphertext
        row.streamer_correl_id_nonce = correl_bundle.nonce
        row.streamer_correl_id_tag = correl_bundle.tag
        row.encrypted_account_hashes = accounts_bundle.ciphertext
        row.account_hashes_nonce = accounts_bundle.nonce
        row.account_hashes_tag = accounts_bundle.tag
        row.streamer_socket_url = "wss://streamer.schwab.com/ws"
        row.mkt_data_permission = "NP"
        session.commit()


def _state_jwt(settings: Any, user_id: int, nonce: str, expired: bool = False) -> str:
    now = datetime.now(UTC)
    exp = now - timedelta(minutes=1) if expired else now + timedelta(minutes=10)
    payload = {
        "sub": str(user_id),
        "purpose": "schwab_oauth",
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _make_prefs_response() -> Any:
    """Return a UserPreferenceResponse-like mock."""
    from app.datasources.schwab_oauth import StreamerInfo, UserPreferenceResponse

    streamer = StreamerInfo(
        streamer_socket_url="wss://streamer.schwab.com/ws",
        schwab_client_customer_id="cust_001",
        schwab_client_correl_id="correl_001",
        schwab_client_channel="IO",
        schwab_client_function_id="APIAPP",
    )
    return UserPreferenceResponse(
        accounts=[
            {
                "accountNumber": "11223344",
                "displayAcctId": "...3344",
                "nickName": "Brokerage",
            }
        ],
        streamer_info=streamer,
        mkt_data_permission="NP",
    )


def _make_account_mappings() -> list[Any]:
    from app.datasources.schwab_oauth import AccountMapping

    return [AccountMapping(account_number="11223344", hash_value="hashed_abc")]


# ---------------------------------------------------------------------------
# GET /broker/schwab/status
# ---------------------------------------------------------------------------


def test_schwab_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/broker/schwab/status")
    assert resp.status_code == 401


def test_schwab_status_connected_false_when_no_credential(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/broker/schwab/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False


def test_schwab_status_connected_true_with_credential(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
) -> None:
    _login(client, test_password)

    # Locate the admin user id
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id

    _seed_schwab_credential(session_factory, user_id, settings.encryption_key_bytes())

    resp = client.get("/api/v1/broker/schwab/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    # Accounts present
    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["display_id"] == "...3344"


def test_schwab_status_does_not_expose_plaintext_account_number(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id
    _seed_schwab_credential(session_factory, user_id, settings.encryption_key_bytes())

    resp = client.get("/api/v1/broker/schwab/status")
    # The raw response text must not contain the plaintext account number
    assert "11223344" not in resp.text


# ---------------------------------------------------------------------------
# GET /broker/schwab/start
# ---------------------------------------------------------------------------


def test_schwab_start_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/broker/schwab/start", follow_redirects=False)
    assert resp.status_code == 401


def test_schwab_start_returns_400_when_not_configured(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    # Default settings fixture has no schwab_client_id → schwab_enabled=False
    resp = client.get("/api/v1/broker/schwab/start", follow_redirects=False)
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "schwab_not_configured"


def test_schwab_start_redirects_with_state_and_sets_nonce_cookie(
    client: TestClient,
    test_password: str,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch settings to enable Schwab
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("test_cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("test_csec"))

    _login(client, test_password)
    resp = client.get("/api/v1/broker/schwab/start", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers["location"]
    # Location starts with the authorize URL
    assert location.startswith(settings.schwab_oauth_authorize_url)
    # Contains client_id
    assert "test_cid" in location
    # Contains redirect_uri and state
    assert "redirect_uri" in location
    assert "state" in location

    # The state JWT must decode to the correct structure
    import urllib.parse

    parsed = urllib.parse.urlparse(location)
    qs = urllib.parse.parse_qs(parsed.query)
    state_jwt = qs["state"][0]
    decoded = jwt.decode(
        state_jwt,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )
    assert decoded["purpose"] == "schwab_oauth"
    assert "nonce" in decoded

    # nonce cookie is set httpOnly
    set_cookie = resp.headers.get("set-cookie", "")
    assert "schwab_oauth_state" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


# ---------------------------------------------------------------------------
# GET /broker/schwab/callback
# ---------------------------------------------------------------------------


def test_schwab_callback_happy_path_stores_credential_and_redirects(
    client: TestClient,
    settings: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    test_password: str,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    # First login to create the admin user
    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id

    nonce = "fixed_nonce_for_test_123"
    state = _state_jwt(settings, user_id, nonce)

    from app.datasources.schwab_oauth import TokenResponse

    good_tokens = TokenResponse(
        access_token="at_new",
        refresh_token="rt_new",
        expires_in=1800,
        scope="api",
        token_type="Bearer",
    )

    with (
        patch(
            "app.api.v1.broker_routes.exchange_code_for_tokens",
            new=AsyncMock(return_value=good_tokens),
        ),
        patch(
            "app.api.v1.broker_routes.get_user_preference",
            new=AsyncMock(return_value=_make_prefs_response()),
        ),
        patch(
            "app.api.v1.broker_routes.get_account_numbers",
            new=AsyncMock(return_value=_make_account_mappings()),
        ),
    ):
        resp = client.get(
            f"/api/v1/broker/schwab/callback?code=good_code&state={state}",
            cookies={"schwab_oauth_state": nonce},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/settings" in resp.headers["location"]
    assert "schwab=connected" in resp.headers["location"]

    # Credential row persisted
    with session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
    assert row is not None

    # Audit log entry
    with session_factory() as session:
        log_row = session.execute(
            select(AuditLog).where(AuditLog.event_type == "schwab.connected")
        ).scalar_one_or_none()
    assert log_row is not None


def test_schwab_callback_nonce_mismatch_redirects_to_error(
    client: TestClient,
    settings: Any,
    session_factory: sessionmaker[Session],
    test_password: str,
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id

    state = _state_jwt(settings, user_id, "nonce_in_jwt")

    resp = client.get(
        f"/api/v1/broker/schwab/callback?code=code&state={state}",
        cookies={"schwab_oauth_state": "DIFFERENT_NONCE"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "schwab=error" in resp.headers["location"]
    assert "bad_state" in resp.headers["location"]


def test_schwab_callback_expired_state_redirects_to_error(
    client: TestClient,
    settings: Any,
    session_factory: sessionmaker[Session],
    test_password: str,
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id

    nonce = "test_nonce_exp"
    expired_state = _state_jwt(settings, user_id, nonce, expired=True)

    resp = client.get(
        f"/api/v1/broker/schwab/callback?code=code&state={expired_state}",
        cookies={"schwab_oauth_state": nonce},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "schwab=error" in resp.headers["location"]


def test_schwab_callback_token_exchange_failure_redirects_to_error(
    client: TestClient,
    settings: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    test_password: str,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id

    nonce = "token_ex_nonce"
    state = _state_jwt(settings, user_id, nonce)

    from app.datasources.schwab_oauth import SchwabOAuthError

    with patch(
        "app.api.v1.broker_routes.exchange_code_for_tokens",
        new=AsyncMock(
            side_effect=SchwabOAuthError("invalid_grant", "Authorization code expired", 400)
        ),
    ):
        resp = client.get(
            f"/api/v1/broker/schwab/callback?code=code&state={state}",
            cookies={"schwab_oauth_state": nonce},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "schwab=error" in resp.headers["location"]
    assert "invalid_grant" in resp.headers["location"]


# ---------------------------------------------------------------------------
# POST /broker/schwab/disconnect
# ---------------------------------------------------------------------------


def test_schwab_disconnect_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/broker/schwab/disconnect")
    assert resp.status_code == 401


def test_schwab_disconnect_deletes_credential_and_returns_204(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id
    _seed_schwab_credential(session_factory, user_id, settings.encryption_key_bytes())

    resp = client.post("/api/v1/broker/schwab/disconnect")
    assert resp.status_code == 204

    with session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
    assert row is None

    # Audit log
    with session_factory() as session:
        log_row = session.execute(
            select(AuditLog).where(AuditLog.event_type == "schwab.disconnected")
        ).scalar_one_or_none()
    assert log_row is not None


def test_schwab_disconnect_idempotent_when_no_credential(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/broker/schwab/disconnect")
    # Implementation returns 204 regardless of whether a row existed
    assert resp.status_code == 204


def test_schwab_disconnect_rate_limit_blocks_eleventh_request(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    for _ in range(10):
        client.post("/api/v1/broker/schwab/disconnect")
    resp = client.post("/api/v1/broker/schwab/disconnect")
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# POST /broker/schwab/test
# ---------------------------------------------------------------------------


def test_schwab_test_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/broker/schwab/test")
    assert resp.status_code == 401


def test_schwab_test_happy_path_returns_success_response(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id
    _seed_schwab_credential(session_factory, user_id, settings.encryption_key_bytes())

    with (
        patch(
            "app.api.v1.broker_routes.get_or_refresh_access_token",
            new=AsyncMock(return_value="live_access_token"),
        ),
        patch(
            "app.api.v1.broker_routes.get_user_preference",
            new=AsyncMock(return_value=_make_prefs_response()),
        ),
    ):
        resp = client.post("/api/v1/broker/schwab/test")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["account_count"] == 1
    assert body["mkt_data_permission"] == "NP"
    assert body["latency_ms"] is not None
    assert body["error"] is None

    # last_test_at + last_test_status persisted
    with session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one()
    assert row.last_test_status == "success"
    assert row.last_test_at is not None


def test_schwab_test_api_error_returns_success_false(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    _login(client, test_password)
    with session_factory() as session:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        user_id = user.id
    _seed_schwab_credential(session_factory, user_id, settings.encryption_key_bytes())

    from app.datasources.schwab_oauth import SchwabApiError

    with (
        patch(
            "app.api.v1.broker_routes.get_or_refresh_access_token",
            new=AsyncMock(return_value="at"),
        ),
        patch(
            "app.api.v1.broker_routes.get_user_preference",
            new=AsyncMock(side_effect=SchwabApiError("unauthorized", "Token invalid", 401)),
        ),
    ):
        resp = client.post("/api/v1/broker/schwab/test")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "unauthorized"

    with session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one()
    assert row.last_test_status == "failed"


def test_schwab_test_reauth_required_returns_reauth_error(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    _login(client, test_password)

    from app.services.schwab_session import SchwabReauthRequired

    with patch(
        "app.api.v1.broker_routes.get_or_refresh_access_token",
        new=AsyncMock(side_effect=SchwabReauthRequired()),
    ):
        resp = client.post("/api/v1/broker/schwab/test")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "reauth_required"


def test_schwab_test_rate_limit_blocks_eleventh_request(
    client: TestClient,
    test_password: str,
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
) -> None:
    monkeypatch.setattr(settings, "schwab_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "schwab_client_secret", SecretStr("csec"))

    _login(client, test_password)

    from app.services.schwab_session import SchwabReauthRequired

    with patch(
        "app.api.v1.broker_routes.get_or_refresh_access_token",
        new=AsyncMock(side_effect=SchwabReauthRequired()),
    ):
        for _ in range(10):
            client.post("/api/v1/broker/schwab/test")
        resp = client.post("/api/v1/broker/schwab/test")
    assert resp.status_code == 429

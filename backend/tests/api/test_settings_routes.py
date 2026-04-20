"""Settings API — password change, audit log, system info, data refresh."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, Trade, User


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


# --- password change ------------------------------------------------------


def test_password_change_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/settings/password",
        json={"current_password": "x", "new_password": "y"},
    )
    assert resp.status_code == 401


def test_password_change_wrong_current_returns_401(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post(
        "/api/v1/settings/password",
        json={"current_password": "nope", "new_password": "Aa1!" * 6},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_password"


def test_password_change_rejects_weak(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post(
        "/api/v1/settings/password",
        json={"current_password": test_password, "new_password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "password_weak"


def test_password_change_succeeds_and_audit_recorded(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    new_pw = "NewStrong!Password2026"
    resp = client.post(
        "/api/v1/settings/password",
        json={"current_password": test_password, "new_password": new_pw},
    )
    assert resp.status_code == 200, resp.text

    # Cookie still valid after password change (we don't rotate here).
    # Now verify login with the NEW password works.
    client.post("/api/v1/logout")
    relogin = client.post("/api/v1/login", json={"username": "admin", "password": new_pw})
    assert relogin.status_code == 200

    # Audit log captured the change — without the password itself.
    with session_factory() as session:
        import sqlalchemy as sa

        rows = (
            session.execute(sa.select(AuditLog).where(AuditLog.event_type == "password.changed"))
            .scalars()
            .all()
        )
    assert rows
    for r in rows:
        body = r.details or {}
        # The sanitizer key list must not accidentally let
        # "current_password"/"new_password" leak.
        assert "current_password" not in body
        assert "new_password" not in body


# --- audit log ------------------------------------------------------------


def test_audit_log_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/settings/audit-log").status_code == 401


def test_audit_log_user_isolation(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    admin_password_hash: str,
) -> None:
    """User B's audit entries must never appear in user A's response."""
    with session_factory() as session:
        bob = User(username="bob", password_hash=admin_password_hash, is_active=True)
        session.add(bob)
        session.flush()
        session.add(
            AuditLog(
                event_type="login.success",
                user_id=bob.id,
                ip="1.2.3.4",
                timestamp=datetime.now(UTC),
                details={"evidence": "bob_only"},
            )
        )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/settings/audit-log?limit=500").json()
    for entry in body["data"]:
        assert "evidence" not in entry["details"]  # bob's row is invisible


def test_audit_log_redacts_secret_keys_in_details(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Belt-and-suspenders: if a caller row has a password-shaped key,
    the API redacts it rather than echoing it back."""
    with session_factory() as session:
        import sqlalchemy as sa

        admin = session.execute(sa.select(User).where(User.username == "admin")).scalar_one()
        session.add(
            AuditLog(
                event_type="bug.synthetic",
                user_id=admin.id,
                ip=None,
                timestamp=datetime.now(UTC),
                details={"password": "SHOULD_REDACT", "note": "ok"},
            )
        )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/settings/audit-log").json()
    synthetic = [e for e in body["data"] if e["event_type"] == "bug.synthetic"]
    assert synthetic
    assert synthetic[0]["details"]["password"] == "[redacted]"
    assert synthetic[0]["details"]["note"] == "ok"


# --- system info ----------------------------------------------------------


def test_system_info_counts_match_fixtures(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    from app.api.v1.settings_routes import _clear_system_info_cache

    _clear_system_info_cache()

    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    client.post("/api/v1/watchlist", json={"symbol": "QQQ"})

    with session_factory() as session:
        import sqlalchemy as sa

        admin = session.execute(sa.select(User).where(User.username == "admin")).scalar_one()
        session.add(
            Trade(
                user_id=admin.id,
                position_id=None,
                symbol="SPY",
                side="buy",
                shares=Decimal("1"),
                price=Decimal("100"),
                executed_at=datetime.now(UTC),
            )
        )
        session.commit()

    _clear_system_info_cache()
    body = client.get("/api/v1/settings/system-info").json()
    assert body["watchlist_count"] == 2
    assert body["trade_count"] == 1
    assert body["positions_count"] == 0
    # admin → user_count populated.
    assert body["user_count"] == 1


# --- manual data refresh --------------------------------------------------


@pytest.mark.asyncio
async def test_data_refresh_returns_job_id_and_records_audit(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/settings/data-refresh")
    assert resp.status_code == 202
    body = resp.json()
    assert body["ok"] is True
    assert body["job_id"]
    assert isinstance(body["market_open"], bool)

    with session_factory() as session:
        import sqlalchemy as sa

        rows = (
            session.execute(sa.select(AuditLog).where(AuditLog.event_type == "data.manual_refresh"))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].details is not None
    assert "job_id" in rows[0].details

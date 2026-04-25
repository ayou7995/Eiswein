"""Tests for app.jobs.schwab_token_refresh — batch Schwab token rotation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.datasources.schwab_oauth import SchwabOAuthError, TokenResponse
from app.db.database import apply_sqlite_pragmas
from app.db.models import Base, BrokerCredential, User
from app.jobs.schwab_token_refresh import run
from app.security.encryption import encrypt
from app.services.schwab_session import _clear_cache_for_tests

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_session_cache_job() -> None:
    _clear_cache_for_tests()
    yield  # type: ignore[misc]
    _clear_cache_for_tests()


@pytest.fixture
def mem_engine():
    from sqlalchemy import event

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(eng, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def mem_sf(mem_engine):
    return sessionmaker(bind=mem_engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture
def job_settings(tmp_path) -> Settings:
    import base64
    import os

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="j" * 80,
        encryption_key=key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash="$2b$04$" + "x" * 53,
        cookie_secure=False,
        schwab_client_id=SecretStr("cid"),
        schwab_client_secret=SecretStr("csec"),
    )


@pytest.fixture
def disabled_settings(job_settings: Settings) -> Settings:
    """Settings with Schwab disabled (no client_id/secret)."""
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="j" * 80,
        encryption_key=job_settings.encryption_key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash="$2b$04$" + "x" * 53,
        cookie_secure=False,
        # No schwab_client_id or schwab_client_secret → schwab_enabled=False
    )


def _seed_user_and_credential(
    session_factory: sessionmaker[Session],
    user_id: int,
    encryption_key: bytes,
    refresh_token: str = "stored_rt",
) -> None:
    bundle = encrypt(refresh_token.encode(), encryption_key)
    with session_factory() as session:
        if not session.get(User, user_id):
            session.add(
                User(
                    id=user_id,
                    username=f"user_{user_id}",
                    password_hash="$2b$04$" + "x" * 53,
                )
            )
        session.add(
            BrokerCredential(
                user_id=user_id,
                broker="schwab",
                encrypted_refresh_token=bundle.ciphertext,
                token_nonce=bundle.nonce,
                token_tag=bundle.tag,
            )
        )
        session.commit()


def _make_token_response(at: str = "new_at", rt: str = "new_rt") -> TokenResponse:
    return TokenResponse(
        access_token=at,
        refresh_token=rt,
        expires_in=1800,
        scope="api",
        token_type="Bearer",
    )


# ---------------------------------------------------------------------------
# Disabled guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_disabled_is_noop(mem_sf, disabled_settings: Settings) -> None:
    counts = await run(session_factory=mem_sf, settings=disabled_settings)
    assert counts == {"users_refreshed": 0, "users_failed": 0, "users_reauth_required": 0}


# ---------------------------------------------------------------------------
# Single credential — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_one_credential_success_increments_refreshed(
    mem_sf, job_settings: Settings
) -> None:
    _seed_user_and_credential(mem_sf, 1, job_settings.encryption_key_bytes())

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(return_value=_make_token_response()),
    ):
        counts = await run(session_factory=mem_sf, settings=job_settings)

    assert counts["users_refreshed"] == 1
    assert counts["users_failed"] == 0
    assert counts["users_reauth_required"] == 0


# ---------------------------------------------------------------------------
# invalid_grant → reauth_required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_invalid_grant_deletes_credential_and_counts_reauth(
    mem_sf, job_settings: Settings
) -> None:
    _seed_user_and_credential(mem_sf, 2, job_settings.encryption_key_bytes())

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(side_effect=SchwabOAuthError("invalid_grant", "Refresh token expired", 400)),
    ):
        counts = await run(session_factory=mem_sf, settings=job_settings)

    assert counts["users_reauth_required"] == 1
    assert counts["users_refreshed"] == 0
    assert counts["users_failed"] == 0

    # Credential row must be deleted
    from sqlalchemy import select

    with mem_sf() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == 2,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
    assert row is None


# ---------------------------------------------------------------------------
# Network error → failed (credential retained)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_network_error_counts_failed_and_retains_credential(
    mem_sf, job_settings: Settings
) -> None:
    _seed_user_and_credential(mem_sf, 3, job_settings.encryption_key_bytes())

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(side_effect=SchwabOAuthError("network_error", "Connection refused", None)),
    ):
        counts = await run(session_factory=mem_sf, settings=job_settings)

    assert counts["users_failed"] == 1
    assert counts["users_reauth_required"] == 0
    assert counts["users_refreshed"] == 0

    # Credential row must still exist
    from sqlalchemy import select

    with mem_sf() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == 3,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
    assert row is not None


# ---------------------------------------------------------------------------
# Multiple users — each handled independently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_multiple_users_each_handled_independently(
    mem_sf, job_settings: Settings
) -> None:
    key = job_settings.encryption_key_bytes()
    _seed_user_and_credential(mem_sf, 10, key)  # will succeed
    _seed_user_and_credential(mem_sf, 11, key)  # will invalid_grant
    _seed_user_and_credential(mem_sf, 12, key)  # will network_error

    call_count = 0

    async def _side_effect(*, client_id, client_secret, refresh_token, **kwargs):
        nonlocal call_count
        call_count += 1
        # We figure out which user based on call order (users come out sorted)
        # Instead, raise different errors for different call counts
        if call_count == 1:
            return _make_token_response()
        if call_count == 2:
            raise SchwabOAuthError("invalid_grant", "Expired", 400)
        if call_count == 3:
            raise SchwabOAuthError("network_error", "Connection refused", None)
        raise RuntimeError("unexpected extra call")

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=_side_effect,
    ):
        counts = await run(session_factory=mem_sf, settings=job_settings)

    assert counts["users_refreshed"] == 1
    assert counts["users_reauth_required"] == 1
    assert counts["users_failed"] == 1
    assert sum(counts.values()) == 3

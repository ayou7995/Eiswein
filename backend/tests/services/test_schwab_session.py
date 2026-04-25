"""Tests for app.services.schwab_session — in-memory token cache + refresh."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.schwab_session as schwab_session
from app import services  # noqa: F401 — ensure module imported before patching
from app.config import Settings
from app.datasources.schwab_oauth import SchwabOAuthError, TokenResponse
from app.db.database import apply_sqlite_pragmas
from app.db.models import Base, BrokerCredential, User
from app.security.encryption import encrypt
from app.services.schwab_session import (
    SchwabReauthRequired,
    _clear_cache_for_tests,
    get_or_refresh_access_token,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_session_cache() -> None:
    """Reset module-level cache + locks before every test."""
    _clear_cache_for_tests()
    yield  # type: ignore[misc]
    _clear_cache_for_tests()


@pytest.fixture
def mem_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlalchemy import event

    event.listen(eng, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def mem_session_factory(mem_engine):
    return sessionmaker(bind=mem_engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture
def schwab_settings(tmp_path) -> Settings:
    import base64
    import os

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="t" * 80,
        encryption_key=key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash="$2b$04$" + "x" * 53,
        cookie_secure=False,
        schwab_client_id=SecretStr("cid"),
        schwab_client_secret=SecretStr("csec"),
    )


def _seed_credential(
    session_factory: sessionmaker[Session],
    user_id: int,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Insert a User + encrypted BrokerCredential into the test DB."""
    key = settings.encryption_key_bytes()
    bundle = encrypt(refresh_token.encode(), key)
    with session_factory() as session:
        # Ensure the user row exists (FK)
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


def _make_token_response(
    access_token: str = "new_at",
    refresh_token: str = "new_rt",
    expires_in: int = 1800,
) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        scope="api",
        token_type="Bearer",
    )


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_cache_hit_skips_upstream_call(
    mem_session_factory,
    schwab_settings,
) -> None:
    # Pre-seed cache with a token that expires far in the future
    schwab_session._token_cache[1] = schwab_session._CachedAccessToken(
        access_token="cached_at",
        expires_at_monotonic=time.monotonic() + 3600,
    )

    with patch("app.services.schwab_session.refresh_access_token") as mock_refresh:
        result = await get_or_refresh_access_token(
            user_id=1,
            session_factory=mem_session_factory,
            settings=schwab_settings,
        )

    assert result == "cached_at"
    mock_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# Cache expired → triggers refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_expired_cache_triggers_refresh(
    mem_session_factory,
    schwab_settings,
) -> None:
    # Seed with an already-expired entry (monotonic in the past)
    schwab_session._token_cache[1] = schwab_session._CachedAccessToken(
        access_token="stale_at",
        expires_at_monotonic=time.monotonic() - 100,
    )
    _seed_credential(mem_session_factory, 1, "stored_rt", schwab_settings)

    new_tokens = _make_token_response("fresh_at", "fresh_rt")
    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(return_value=new_tokens),
    ):
        result = await get_or_refresh_access_token(
            user_id=1,
            session_factory=mem_session_factory,
            settings=schwab_settings,
        )

    assert result == "fresh_at"
    # New token must be cached
    assert schwab_session._token_cache[1].access_token == "fresh_at"


# ---------------------------------------------------------------------------
# Cold cache → refresh + cache written + refresh token persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_cold_cache_fetches_and_caches(
    mem_session_factory,
    schwab_settings,
) -> None:
    _seed_credential(mem_session_factory, 2, "original_rt", schwab_settings)

    new_tokens = _make_token_response("brand_new_at", "brand_new_rt")
    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(return_value=new_tokens),
    ):
        result = await get_or_refresh_access_token(
            user_id=2,
            session_factory=mem_session_factory,
            settings=schwab_settings,
        )

    assert result == "brand_new_at"
    assert schwab_session._token_cache[2].access_token == "brand_new_at"


# ---------------------------------------------------------------------------
# Rotated refresh token is persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_rotated_refresh_token_stored(
    mem_session_factory,
    schwab_settings,
) -> None:
    _seed_credential(mem_session_factory, 3, "old_rt", schwab_settings)

    rotated_tokens = _make_token_response("at_v2", "rotated_rt_v2")
    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(return_value=rotated_tokens),
    ):
        await get_or_refresh_access_token(
            user_id=3,
            session_factory=mem_session_factory,
            settings=schwab_settings,
        )

    # Verify the rotated refresh token was written back to the DB
    key = schwab_settings.encryption_key_bytes()
    from app.db.repositories.broker_credential_repository import BrokerCredentialRepository

    with mem_session_factory() as session:
        repo = BrokerCredentialRepository(session, key)
        stored = repo.load_refresh_token(user_id=3, broker="schwab")
    assert stored == "rotated_rt_v2"


# ---------------------------------------------------------------------------
# invalid_grant → credential deleted + SchwabReauthRequired raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_invalid_grant_deletes_credential_and_raises(
    mem_session_factory,
    schwab_settings,
) -> None:
    _seed_credential(mem_session_factory, 4, "dead_rt", schwab_settings)

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=AsyncMock(side_effect=SchwabOAuthError("invalid_grant", "Refresh token expired", 400)),
    ):
        with pytest.raises(SchwabReauthRequired):
            await get_or_refresh_access_token(
                user_id=4,
                session_factory=mem_session_factory,
                settings=schwab_settings,
            )

    # Credential row must be gone
    from sqlalchemy import select

    with mem_session_factory() as session:
        row = session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == 4,
                BrokerCredential.broker == "schwab",
            )
        ).scalar_one_or_none()
    assert row is None

    # In-memory cache must also be cleared
    assert 4 not in schwab_session._token_cache


# ---------------------------------------------------------------------------
# Concurrency — per-user lock collapses parallel requests into one upstream call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_refresh_concurrent_calls_collapse_to_one_upstream(
    mem_session_factory,
    schwab_settings,
) -> None:
    _seed_credential(mem_session_factory, 5, "shared_rt", schwab_settings)

    call_count = 0
    results_returned: list[str] = []

    async def _slow_refresh(**kwargs: object) -> TokenResponse:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return _make_token_response("shared_at", "shared_rt_new")

    with patch(
        "app.services.schwab_session.refresh_access_token",
        new=_slow_refresh,
    ):
        tokens = await asyncio.gather(
            *[
                get_or_refresh_access_token(
                    user_id=5,
                    session_factory=mem_session_factory,
                    settings=schwab_settings,
                )
                for _ in range(5)
            ]
        )
        results_returned.extend(tokens)

    # Exactly one upstream call despite 5 concurrent waiters
    assert call_count == 1
    # All 5 callers received the same token
    assert all(t == "shared_at" for t in results_returned)

"""In-process access-token cache + refresh helper for Schwab.

The access token is a 30-minute bearer secret that must NOT be
persisted (``oauth.md`` + ``security_reference.md``). We keep it in a
module-level dict keyed by ``user_id`` so the FastAPI route handler
and the 20-minute refresh scheduler can share cached tokens for the
same process. Single-process lock (uvicorn ``--workers 1``) means we
don't need distributed cache coordination.

Concurrency
-----------
Two invariants:

1. One in-flight refresh per user. We hold a per-user ``asyncio.Lock``
   around the refresh call so concurrent ``get_or_refresh_access_token``
   callers collapse to a single upstream request. Without this, two
   parallel requests would each mint their own access token and one
   would immediately discard the other's new refresh-token rotation,
   losing a credential.
2. Cache writes are done under that same per-user lock. Reads outside
   the lock are safe because dict item assignment is atomic in
   CPython — worst case a reader sees a stale token whose TTL hasn't
   elapsed yet, which is fine.

Re-auth signal
--------------
When Schwab returns ``invalid_grant`` on the refresh call, the stored
refresh token is past its 7-day TTL (or revoked). We delete the
credential row and raise :class:`SchwabReauthRequired` so the caller
surfaces the "reconnect Schwab" UI state. Never silently proceed —
a dangling BrokerCredential row with a dead refresh token is a trap
for users.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.datasources.schwab_oauth import (
    SchwabOAuthError,
    TokenResponse,
    refresh_access_token,
)
from app.db.models import BrokerCredential
from app.db.repositories.broker_credential_repository import BrokerCredentialRepository

logger = structlog.get_logger("eiswein.services.schwab_session")


class SchwabReauthRequired(Exception):
    """Raised when the refresh token is no longer valid.

    The caller deletes the credential (already done by the helper
    itself before raising) and directs the user through the OAuth
    ``/start`` flow again. This is a normal outcome after the 7-day
    refresh-token TTL expires, so it's not treated as an error in
    structured logs.
    """


@dataclass(frozen=True, slots=True)
class _CachedAccessToken:
    """Access token held in memory only, never serialized."""

    access_token: str
    expires_at_monotonic: float


# Module-level cache — one entry per user_id. Reset by tests via
# ``_clear_cache_for_tests``. Never exposed outside this module.
_token_cache: dict[int, _CachedAccessToken] = {}
_user_locks: dict[int, asyncio.Lock] = {}

# 60s buffer: returning a token that expires in 20s is a footgun —
# the caller makes one Schwab call, succeeds, makes another, and by then
# it's dead. 60s of headroom covers normal request latency plus a small
# clock-skew budget.
_EXPIRY_BUFFER_SECONDS = 60.0


def _clear_cache_for_tests() -> None:
    _token_cache.clear()
    _user_locks.clear()


def clear_cached_access_token(user_id: int) -> None:
    """Drop any cached access token + lock for ``user_id``.

    Used by the disconnect path so a pending refresh flow can't
    resurrect a dead credential. Always safe (no-op if absent).
    """
    _token_cache.pop(user_id, None)
    _user_locks.pop(user_id, None)


def _get_user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


async def get_or_refresh_access_token(
    *,
    user_id: int,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> str:
    """Return a live access token, refreshing from Schwab if needed.

    Raises :class:`SchwabReauthRequired` if the stored refresh token
    has been invalidated (Schwab ``invalid_grant``). Raises
    :class:`SchwabOAuthError` for any other failure so the caller can
    distinguish network blips (retry later) from credential death
    (surface re-auth UI).
    """
    cached = _token_cache.get(user_id)
    now = time.monotonic()
    if cached is not None and cached.expires_at_monotonic - now > _EXPIRY_BUFFER_SECONDS:
        return cached.access_token

    if not settings.schwab_enabled:
        raise SchwabOAuthError("schwab_not_configured", "schwab is not configured", None)

    lock = _get_user_lock(user_id)
    async with lock:
        # Double-check inside the lock — another coroutine may have
        # refreshed while we were waiting.
        cached = _token_cache.get(user_id)
        now = time.monotonic()
        if cached is not None and cached.expires_at_monotonic - now > _EXPIRY_BUFFER_SECONDS:
            return cached.access_token

        # Load the refresh token under a short-lived session.
        refresh_token_plain = _load_refresh_token(
            user_id=user_id,
            session_factory=session_factory,
            key_bytes=settings.encryption_key_bytes(),
        )
        if refresh_token_plain is None:
            raise SchwabReauthRequired()

        client_id = _require_secret(settings.schwab_client_id, "schwab_client_id")
        client_secret = _require_secret(settings.schwab_client_secret, "schwab_client_secret")

        try:
            tokens = await refresh_access_token(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token_plain,
            )
        except SchwabOAuthError as exc:
            if exc.code == "invalid_grant":
                _delete_credential(
                    user_id=user_id,
                    session_factory=session_factory,
                )
                logger.warning(
                    "schwab_reauth_required",
                    user_id=user_id,
                    reason="invalid_grant_on_refresh",
                )
                raise SchwabReauthRequired() from exc
            raise

        _persist_rotated_tokens(
            user_id=user_id,
            session_factory=session_factory,
            key_bytes=settings.encryption_key_bytes(),
            tokens=tokens,
        )

        expires_at = time.monotonic() + max(tokens.expires_in - _EXPIRY_BUFFER_SECONDS, 0.0)
        _token_cache[user_id] = _CachedAccessToken(
            access_token=tokens.access_token,
            expires_at_monotonic=expires_at,
        )
        return tokens.access_token


def _load_refresh_token(
    *,
    user_id: int,
    session_factory: sessionmaker[Session],
    key_bytes: bytes,
) -> str | None:
    with session_factory() as session:
        repo = BrokerCredentialRepository(session, key_bytes)
        return repo.load_refresh_token(user_id=user_id, broker="schwab")


def _persist_rotated_tokens(
    *,
    user_id: int,
    session_factory: sessionmaker[Session],
    key_bytes: bytes,
    tokens: TokenResponse,
) -> None:
    """Write-through the (possibly rotated) refresh token + stamp last_refreshed_at.

    Schwab may return a new refresh token on every refresh call. We
    always overwrite even when the returned value matches — the
    encryption nonce rotation alone makes this worth the write.
    """
    from datetime import UTC, datetime, timedelta

    expires_at = datetime.now(UTC) + timedelta(days=7)
    with session_factory() as session:
        repo = BrokerCredentialRepository(session, key_bytes)
        repo.store_refresh_token(
            user_id=user_id,
            broker="schwab",
            refresh_token=tokens.refresh_token,
            expires_at=expires_at,
        )
        repo.touch_last_refreshed(user_id)
        session.commit()


def _delete_credential(
    *,
    user_id: int,
    session_factory: sessionmaker[Session],
) -> None:
    """Drop the stored refresh token + clear the cache entry.

    Called when the refresh token is dead beyond recovery. The cache
    wipe prevents a stale in-memory access token from outliving its
    refresh token.
    """
    _token_cache.pop(user_id, None)
    with session_factory() as session:
        session.execute(
            delete(BrokerCredential).where(
                BrokerCredential.user_id == user_id,
                BrokerCredential.broker == "schwab",
            )
        )
        session.commit()


def _require_secret(value: object, label: str) -> str:
    """Resolve a ``SecretStr | None`` config field to a non-empty string."""
    if value is None:
        raise SchwabOAuthError("schwab_not_configured", f"{label} is not set", None)
    from pydantic import SecretStr

    if isinstance(value, SecretStr):
        plain = value.get_secret_value()
        if not plain:
            raise SchwabOAuthError("schwab_not_configured", f"{label} is empty", None)
        return plain
    raise SchwabOAuthError("schwab_not_configured", f"{label} is not a secret", None)


__all__: tuple[str, ...] = (
    "SchwabReauthRequired",
    "_clear_cache_for_tests",
    "get_or_refresh_access_token",
)

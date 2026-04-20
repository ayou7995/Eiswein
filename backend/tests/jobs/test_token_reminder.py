"""Tests for :mod:`app.jobs.token_reminder`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import User
from app.db.repositories.broker_credential_repository import BrokerCredentialRepository
from app.jobs import token_reminder


def _seed_user(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        user = User(
            username="admin",
            password_hash="$2b$12$" + "a" * 53,
            is_admin=True,
        )
        session.add(user)
        session.commit()
        return int(user.id)


@pytest.mark.asyncio
async def test_no_credentials_logs_skipped(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    with patch.object(token_reminder, "send_token_expiry_alert") as send_mock:
        sent = await token_reminder.run(
            session_factory=session_factory,
            settings=settings,
        )
    assert sent == 0
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_credential_within_two_days_triggers_alert(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    user_id = _seed_user(session_factory)

    with session_factory() as session:
        BrokerCredentialRepository(session, settings.encryption_key_bytes()).store_refresh_token(
            user_id=user_id,
            broker="schwab",
            refresh_token="fake-token-xyz",
            expires_at=datetime.now(UTC) + timedelta(hours=30),
        )
        session.commit()

    with patch.object(token_reminder, "send_token_expiry_alert", return_value=True) as send_mock:
        sent = await token_reminder.run(
            session_factory=session_factory,
            settings=settings,
        )
    assert sent == 1
    send_mock.assert_called_once()
    kwargs = send_mock.call_args.kwargs
    assert kwargs["broker"] == "schwab"
    assert kwargs["days_remaining"] <= 2


@pytest.mark.asyncio
async def test_credential_outside_window_is_ignored(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    user_id = _seed_user(session_factory)

    with session_factory() as session:
        BrokerCredentialRepository(session, settings.encryption_key_bytes()).store_refresh_token(
            user_id=user_id,
            broker="schwab",
            refresh_token="fake-token-xyz",
            expires_at=datetime.now(UTC) + timedelta(days=10),
        )
        session.commit()

    with patch.object(token_reminder, "send_token_expiry_alert") as send_mock:
        sent = await token_reminder.run(
            session_factory=session_factory,
            settings=settings,
        )
    assert sent == 0
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_failure_returns_zero_but_no_raise(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    user_id = _seed_user(session_factory)
    with session_factory() as session:
        BrokerCredentialRepository(session, settings.encryption_key_bytes()).store_refresh_token(
            user_id=user_id,
            broker="schwab",
            refresh_token="x",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.commit()

    with patch.object(token_reminder, "send_token_expiry_alert", return_value=False):
        sent = await token_reminder.run(
            session_factory=session_factory,
            settings=settings,
        )
    assert sent == 0


@pytest.mark.asyncio
async def test_naive_expires_at_is_treated_as_utc(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    user_id = _seed_user(session_factory)
    # Store a credential via direct model insert so we can put a naive datetime.
    from app.db.models import BrokerCredential

    with session_factory() as session:
        session.add(
            BrokerCredential(
                user_id=user_id,
                broker="schwab",
                encrypted_refresh_token=b"c",
                token_nonce=b"n" * 12,
                token_tag=b"t" * 16,
                expires_at=datetime.utcnow() + timedelta(hours=12),
            )
        )
        session.commit()

    with patch.object(token_reminder, "send_token_expiry_alert", return_value=True) as send_mock:
        sent = await token_reminder.run(
            session_factory=session_factory,
            settings=settings,
        )
    assert sent == 1
    kwargs = send_mock.call_args.kwargs
    assert kwargs["expires_at"].tzinfo is not None

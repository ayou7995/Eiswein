"""Bcrypt + JWT + IP-throttle unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.security.exceptions import TokenExpiredError, TokenInvalidError
from app.security.login_throttle import (
    AttemptRecord,
    evaluate_ip_lockout,
    global_failure_count,
)

SECRET = "a" * 64


def test_bcrypt_roundtrip() -> None:
    h = hash_password("correcthorsebatterystaple")
    assert verify_password("correcthorsebatterystaple", h) is True
    assert verify_password("wrong", h) is False


def test_bcrypt_rejects_empty_password() -> None:
    assert verify_password("", "$2b$12$abc") is False


def test_hash_password_rejects_empty() -> None:
    from app.security.exceptions import InvalidCredentialsError

    with pytest.raises(InvalidCredentialsError):
        hash_password("")


def test_jwt_access_roundtrip() -> None:
    token = create_access_token("42", secret=SECRET, minutes=5)
    payload = decode_token(token, secret=SECRET, expected_type="access")
    assert payload.subject == "42"
    assert payload.token_type == "access"


def test_jwt_refresh_is_rejected_as_access() -> None:
    token = create_refresh_token("42", secret=SECRET, days=7)
    with pytest.raises(TokenInvalidError):
        decode_token(token, secret=SECRET, expected_type="access")


def test_jwt_expired_token_rejected() -> None:
    token = create_access_token("42", secret=SECRET, minutes=-1)
    with pytest.raises(TokenExpiredError):
        decode_token(token, secret=SECRET, expected_type="access")


def test_jwt_tampered_signature_rejected() -> None:
    token = create_access_token("42", secret=SECRET, minutes=5)
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(TokenInvalidError):
        decode_token(tampered, secret=SECRET)


def test_ip_lockout_triggers_after_threshold() -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    attempts = [
        AttemptRecord(ip="1.2.3.4", success=False, timestamp=now - timedelta(seconds=i * 5))
        for i in range(5)
    ]
    status = evaluate_ip_lockout(
        "1.2.3.4",
        attempts,
        threshold=5,
        window=timedelta(minutes=15),
        now=now,
    )
    assert status.locked is True
    assert status.retry_after_seconds > 0
    assert status.attempts_remaining == 0


def test_ip_lockout_resets_after_success() -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    attempts = [
        AttemptRecord(ip="1.2.3.4", success=True, timestamp=now - timedelta(seconds=1)),
        AttemptRecord(ip="1.2.3.4", success=False, timestamp=now - timedelta(seconds=10)),
        AttemptRecord(ip="1.2.3.4", success=False, timestamp=now - timedelta(seconds=20)),
    ]
    status = evaluate_ip_lockout(
        "1.2.3.4",
        attempts,
        threshold=2,
        window=timedelta(minutes=15),
        now=now,
    )
    assert status.locked is False
    assert status.attempts_remaining == 2


def test_ip_lockout_isolated_per_ip() -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    attempts = [
        AttemptRecord(ip="1.2.3.4", success=False, timestamp=now - timedelta(seconds=i))
        for i in range(5)
    ]
    status = evaluate_ip_lockout(
        "5.6.7.8",
        attempts,
        threshold=5,
        window=timedelta(minutes=15),
        now=now,
    )
    assert status.locked is False
    assert status.attempts_remaining == 5


def test_global_failure_count_windowed() -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    attempts = [
        AttemptRecord(ip=f"10.0.0.{i}", success=False, timestamp=now - timedelta(seconds=10))
        for i in range(25)
    ]
    count = global_failure_count(attempts, window=timedelta(minutes=1), now=now)
    assert count == 25

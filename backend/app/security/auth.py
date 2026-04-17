"""Authentication primitives.

Responsibilities
----------------
* bcrypt (12 rounds) password hashing + constant-time verification
* JWT (HS256) access/refresh token issuance + verification
* IP-based login throttling (E5: lock IP, not account)

Decisions
---------
* Token rotation on every login (E2) — call `create_access_token` /
  `create_refresh_token` each time. Old tokens expire naturally.
* Tokens are stateless; no server-side revocation list in v1.
* The IP throttler stores counters in the `audit_log` table (via the
  repository) — no in-memory state, so it survives process restarts
  and is consistent across concurrent requests.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.security.exceptions import (
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
)

BCRYPT_ROUNDS = 12
_TOKEN_TYPES: tuple[Literal["access"], Literal["refresh"]] = ("access", "refresh")


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded JWT payload — immutable snapshot."""

    subject: str
    token_type: Literal["access", "refresh"]
    jti: str
    issued_at: datetime
    expires_at: datetime


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise InvalidCredentialsError("password must not be empty")
    return bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    if not plaintext or not password_hash:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    *,
    subject: str,
    token_type: Literal["access", "refresh"],
    secret: str,
    algorithm: str,
    lifetime: timedelta,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    # jose.jwt.encode is typed as Any in the stubs; we guarantee str.
    token: str = jwt.encode(payload, secret, algorithm=algorithm)
    return token


def create_access_token(
    subject: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    minutes: int = 15,
) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        secret=secret,
        algorithm=algorithm,
        lifetime=timedelta(minutes=minutes),
    )


def create_refresh_token(
    subject: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    days: int = 7,
) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        secret=secret,
        algorithm=algorithm,
        lifetime=timedelta(days=days),
    )


def decode_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    expected_type: Literal["access", "refresh"] | None = None,
) -> TokenPayload:
    try:
        raw = jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise TokenExpiredError() from exc
        raise TokenInvalidError(str(exc)) from exc
    token_type = raw.get("typ")
    if token_type not in _TOKEN_TYPES:
        raise TokenInvalidError("unknown token type")
    if expected_type is not None and token_type != expected_type:
        raise TokenInvalidError(f"expected {expected_type} token, got {token_type}")
    subject = raw.get("sub")
    jti = raw.get("jti")
    iat = raw.get("iat")
    exp = raw.get("exp")
    if not subject or not jti or iat is None or exp is None:
        raise TokenInvalidError("token payload missing required claims")
    return TokenPayload(
        subject=str(subject),
        token_type=token_type,
        jti=str(jti),
        issued_at=datetime.fromtimestamp(int(iat), tz=UTC),
        expires_at=datetime.fromtimestamp(int(exp), tz=UTC),
    )


def generate_jti() -> str:
    """Deterministic-format random jti (use when manually crafting refresh tokens)."""
    return uuid.uuid4().hex


def constant_time_compare(a: str, b: str) -> bool:
    """Short wrapper kept for intent-revealing call sites."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

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
import zxcvbn
from jose import JWTError, jwt

from app.security.exceptions import (
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    ValidationError,
)

BCRYPT_ROUNDS = 12
_TOKEN_TYPES: tuple[Literal["access"], Literal["refresh"]] = ("access", "refresh")

# Password strength policy (docs/STAFF_REVIEW_DECISIONS.md E1):
#   * zxcvbn score >= 3, OR
#   * length >= 12 with at least three of {upper, lower, digit, symbol}.
# The "OR" lets users bypass a short-but-pronounceable zxcvbn false
# positive by typing a long mixed-class password; either gate alone is
# strong enough for the single-user threat model.
_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MIN_ZXCVBN_SCORE = 3
_PASSWORD_MAX_LENGTH = 256


class WeakPasswordError(ValidationError):
    code = "password_weak"
    message = "密碼強度不足"


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


def _has_mixed_character_classes(plaintext: str, *, min_classes: int = 3) -> bool:
    classes = 0
    if any(c.islower() for c in plaintext):
        classes += 1
    if any(c.isupper() for c in plaintext):
        classes += 1
    if any(c.isdigit() for c in plaintext):
        classes += 1
    if any(not c.isalnum() for c in plaintext):
        classes += 1
    return classes >= min_classes


def validate_password_strength(plaintext: str, *, user_inputs: list[str] | None = None) -> None:
    """Raise :class:`WeakPasswordError` if ``plaintext`` fails policy.

    Satisfies the Eiswein password policy (E1): zxcvbn score >= 3 OR
    (length >= 12 with 3+ character classes). ``user_inputs`` is
    passed to zxcvbn to penalize passwords containing the username
    or email — the caller is responsible for forwarding those.
    """
    if not plaintext:
        raise WeakPasswordError(details={"reason": "empty"})
    if len(plaintext) > _PASSWORD_MAX_LENGTH:
        raise WeakPasswordError(details={"reason": "too_long", "max_length": _PASSWORD_MAX_LENGTH})

    long_and_mixed = len(plaintext) >= _PASSWORD_MIN_LENGTH and _has_mixed_character_classes(
        plaintext
    )
    if long_and_mixed:
        return

    # zxcvbn is untyped; treat the result defensively.
    result = zxcvbn.zxcvbn(plaintext, user_inputs=user_inputs or [])
    score = int(result.get("score", 0))
    if score >= _PASSWORD_MIN_ZXCVBN_SCORE:
        return

    # DO NOT include the password or a password hint in details — even
    # zxcvbn's "feedback.suggestions" can echo back the input (e.g.
    # "add more words"). Surface the score so the UI can show a meter.
    raise WeakPasswordError(
        details={
            "reason": "insufficient_entropy",
            "score": score,
            "min_score": _PASSWORD_MIN_ZXCVBN_SCORE,
            "min_length": _PASSWORD_MIN_LENGTH,
        }
    )

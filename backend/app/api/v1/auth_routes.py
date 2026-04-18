"""Auth routes: login, refresh, logout, me.

Key invariants
--------------
* Login returns JWT ONLY in Set-Cookie (httpOnly, SameSite=Lax, Secure).
  NEVER in the response body (B1, E4).
* Fresh tokens are issued on every login (E2).
* IP-based throttling (E5): 5 fails / 15 min per IP. Global 20/min
  emits an audit log entry for the alert pipeline.
* Every attempt is recorded in the audit log.
* Response envelopes match the frontend Zod schemas: {ok, user?} for
  session-bearing responses; {ok} for fire-and-forget responses.

Note: this module intentionally does NOT use `from __future__ import
annotations`. slowapi's @limiter.limit wraps the login handler, and
FastAPI needs runtime access to `LoginRequest` as a real class (not a
string) because the wrapper's __globals__ differs from this module's
and forward-ref resolution fails otherwise.
"""

from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import (
    COOKIE_ACCESS,
    COOKIE_REFRESH,
    current_user_id,
    get_audit_repository,
    get_settings_dep,
    get_user_repository,
)
from app.config import Settings
from app.db.repositories.audit_repository import (
    LOGIN_FAILURE,
    LOGIN_LOCKOUT,
    LOGIN_SUCCESS,
    LOGOUT,
    TOKEN_REFRESH,
    AuditRepository,
)
from app.db.repositories.user_repository import UserRepository
from app.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.security.exceptions import (
    AccountLockedError,
    AuthError,
    InvalidCredentialsError,
    TokenInvalidError,
)
from app.security.login_throttle import (
    evaluate_ip_lockout,
    global_failure_count,
)
from app.security.rate_limit import limiter

router = APIRouter(tags=["auth"])
logger = structlog.get_logger("eiswein.auth")

# Wider than login_lockout_minutes: we want enough history to compute
# attempts_remaining for the attempted IP even across lockout-window
# boundaries. Narrowing this would cause an off-by-one on the
# attempts_remaining count exposed to the client.
_AUDIT_FETCH_WINDOW = timedelta(hours=1)
_GLOBAL_WINDOW = timedelta(minutes=1)


class UserSummary(BaseModel):
    username: str
    is_admin: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserSummary


class SessionResponse(BaseModel):
    ok: bool = True


class MeResponse(BaseModel):
    ok: bool = True
    user: UserSummary


def _client_ip(request: Request) -> str | None:
    ip = getattr(request.state, "client_ip", None)
    if isinstance(ip, str) and ip:
        return ip
    return request.client.host if request.client else None


def _set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=COOKIE_ACCESS,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
        max_age=settings.jwt_access_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key=COOKIE_REFRESH,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
        max_age=settings.jwt_refresh_days * 24 * 60 * 60,
        path="/api/v1/",
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_ACCESS, path="/", domain=settings.cookie_domain)
    response.delete_cookie(COOKIE_REFRESH, path="/api/v1/", domain=settings.cookie_domain)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange username + password for auth cookies",
)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    settings: Settings = Depends(get_settings_dep),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> LoginResponse:
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent")

    recent = audit.recent_login_attempts(window=_AUDIT_FETCH_WINDOW)

    if ip is not None:
        lockout = evaluate_ip_lockout(
            ip,
            recent,
            threshold=settings.login_lockout_threshold,
            window=timedelta(minutes=settings.login_lockout_minutes),
        )
        if lockout.locked:
            audit.record(
                LOGIN_LOCKOUT,
                ip=ip,
                user_agent=user_agent,
                details={"retry_after_seconds": lockout.retry_after_seconds},
            )
            raise AccountLockedError(details={"retry_after_seconds": lockout.retry_after_seconds})

    user = users.by_username(payload.username)
    valid_password = user is not None and verify_password(payload.password, user.password_hash)

    if user is None or not user.is_active or not valid_password:
        audit.record(
            LOGIN_FAILURE,
            user_id=user.id if user else None,
            ip=ip,
            user_agent=user_agent,
            details={"reason": "bad_credentials"},
        )
        failures = global_failure_count(
            audit.recent_login_attempts(window=_GLOBAL_WINDOW),
            window=_GLOBAL_WINDOW,
        )
        if failures >= settings.login_global_alert_per_min:
            audit.record(
                "login.global_threshold_exceeded",
                ip=ip,
                details={"failures_per_minute": failures},
            )
            logger.warning("login_global_threshold_exceeded", failures=failures)
        lockout_after = evaluate_ip_lockout(
            ip or "",
            audit.recent_login_attempts(window=_AUDIT_FETCH_WINDOW),
            threshold=settings.login_lockout_threshold,
            window=timedelta(minutes=settings.login_lockout_minutes),
        )
        raise InvalidCredentialsError(
            details={"attempts_remaining": lockout_after.attempts_remaining}
        )

    access = create_access_token(
        subject=str(user.id),
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        minutes=settings.jwt_access_minutes,
    )
    refresh = create_refresh_token(
        subject=str(user.id),
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        days=settings.jwt_refresh_days,
    )
    _set_auth_cookies(response, access_token=access, refresh_token=refresh, settings=settings)

    users.record_successful_login(user, ip=ip)
    audit.record(
        LOGIN_SUCCESS,
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    return LoginResponse(user=UserSummary(username=user.username, is_admin=user.is_admin))


@router.post(
    "/refresh",
    response_model=SessionResponse,
    summary="Rotate access token using refresh cookie",
)
def refresh_token(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> SessionResponse:
    refresh_cookie = request.cookies.get(COOKIE_REFRESH)
    if not refresh_cookie:
        raise AuthError()
    payload = decode_token(
        refresh_cookie,
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        expected_type="refresh",
    )
    try:
        user_id = int(payload.subject)
    except ValueError as exc:
        raise TokenInvalidError("invalid subject") from exc
    user = users.by_id(user_id)
    if user is None or not user.is_active:
        raise AuthError()

    access = create_access_token(
        subject=str(user.id),
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        minutes=settings.jwt_access_minutes,
    )
    refresh = create_refresh_token(
        subject=str(user.id),
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        days=settings.jwt_refresh_days,
    )
    _set_auth_cookies(response, access_token=access, refresh_token=refresh, settings=settings)
    audit.record(TOKEN_REFRESH, user_id=user.id, ip=_client_ip(request))
    return SessionResponse()


@router.post(
    "/logout",
    response_model=SessionResponse,
    summary="Clear auth cookies",
)
def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
    audit: AuditRepository = Depends(get_audit_repository),
) -> SessionResponse:
    user_id: int | None = None
    access_cookie = request.cookies.get(COOKIE_ACCESS)
    if access_cookie:
        try:
            payload = decode_token(
                access_cookie,
                secret=settings.jwt_secret.get_secret_value(),
                algorithm=settings.jwt_algorithm,
                expected_type="access",
            )
            user_id = int(payload.subject)
        except (AuthError, ValueError):
            user_id = None
    _clear_auth_cookies(response, settings)
    audit.record(LOGOUT, user_id=user_id, ip=_client_ip(request))
    return SessionResponse()


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the currently-authenticated user",
)
def me(
    user_id: int = Depends(current_user_id),
    users: UserRepository = Depends(get_user_repository),
) -> MeResponse:
    user = users.by_id(user_id)
    if user is None or not user.is_active:
        raise AuthError()
    return MeResponse(user=UserSummary(username=user.username, is_admin=user.is_admin))

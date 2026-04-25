"""Broker connect/disconnect/test endpoints — Schwab OAuth flow.

This module wires the four Phase-S1 routes listed in the Workstream A
plan:

* ``GET /broker/schwab/start``      — kick off the three-legged dance.
* ``GET /broker/schwab/callback``   — handle the redirect from Schwab.
* ``POST /broker/schwab/disconnect``— delete the stored credential.
* ``GET /broker/schwab/status``     — read-only UI state.
* ``POST /broker/schwab/test``      — live ``/userPreference`` probe.

CSRF defense — state JWT + cookie nonce
---------------------------------------
The OAuth ``state`` parameter is a short-lived JWT signed with
``JWT_SECRET``. It carries ``{user_id, nonce, purpose, exp}``. On
``/start`` we also drop an ``httpOnly`` cookie containing the same
nonce. On ``/callback`` we require BOTH the JWT signature to verify
AND the cookie nonce to match the JWT claim. The cookie binding
prevents an attacker who captures a ``state`` JWT in a log or URL
from replaying the callback from a different browser — they'd need
to also steal the user's cookie jar, which is the standard SameSite
= Lax protection.

We deliberately do NOT keep a server-side nonce set. An in-memory Set
would not survive a process restart and is redundant when the JWT is
itself single-use (bound to a ``nonce``, a 10-min ``exp``, and a
cookie). Rejecting replay is enforced by the cookie expiry, not by
a server-side registry.

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
Same pattern as ``auth_routes.py``: slowapi's ``@limiter.limit``
wrapper needs ``Request`` / ``BackgroundTasks`` to resolve at import
time, and forward-ref resolution fails when the wrapper's
``__globals__`` differs from ours.
"""

import asyncio
import secrets
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    current_user_id,
    get_audit_repository,
    get_broker_credential_repository,
    get_db_session,
    get_settings_dep,
)
from app.config import Settings
from app.datasources.schwab_oauth import (
    AccountMapping,
    SchwabApiError,
    SchwabOAuthError,
    UserPreferenceResponse,
    exchange_code_for_tokens,
    get_account_numbers,
    get_user_preference,
)
from app.db.models import BrokerCredential
from app.db.repositories.audit_repository import (
    SCHWAB_CONNECTED,
    SCHWAB_DISCONNECTED,
    SCHWAB_REAUTH_REQUIRED,
    AuditRepository,
)
from app.db.repositories.broker_credential_repository import BrokerCredentialRepository
from app.security.exceptions import EisweinError
from app.security.rate_limit import limiter
from app.services.schwab_session import (
    SchwabReauthRequired,
    clear_cached_access_token,
    get_or_refresh_access_token,
)

router = APIRouter(prefix="/broker", tags=["broker"])
logger = structlog.get_logger("eiswein.api.broker")

_STATE_COOKIE_NAME = "schwab_oauth_state"
_STATE_TTL_SECONDS = 600  # 10 minutes
_STATE_PURPOSE = "schwab_oauth"

# Map Schwab error codes to sanitized user-facing messages.
# NEVER forward the raw `exc.message` from an upstream error — it may
# include correlation IDs or internal hints not meant for end users.
_SAFE_TEST_MESSAGES: dict[str, str] = {
    "invalid_grant": "Schwab 授權憑證已失效，請重新連接",
    "invalid_client": "Schwab API key 設定有誤，請檢查系統設定",
    "network_error": "無法連線至 Schwab，請稍後再試",
    "server_error": "Schwab 伺服器暫時無法服務，請稍後再試",
    "unknown": "Schwab 連線測試失敗",
}


def _safe_test_message(code: str) -> str:
    """Translate an exception code into a safe user-facing message."""
    return _SAFE_TEST_MESSAGES.get(code, _SAFE_TEST_MESSAGES["unknown"])


# --- Error types ----------------------------------------------------------


class SchwabNotConfiguredError(EisweinError):
    """Thrown when ``/start`` fires without Schwab creds in settings.

    400 (not 500) — it's a configuration precondition, not a crash.
    The UI renders it as a "連接功能尚未啟用" banner.
    """

    http_status = 400
    code = "schwab_not_configured"
    message = "Schwab 尚未完成設定"


class SchwabOAuthStateError(EisweinError):
    """Invalid / expired / tampered-with OAuth ``state`` parameter.

    Raised by ``/callback`` — the browser is redirected to the error
    page without attempting the token exchange.
    """

    http_status = 400
    code = "schwab_oauth_state"
    message = "OAuth state 驗證失敗，請重新連接"


# --- Response schemas -----------------------------------------------------


class SchwabAccountSummary(BaseModel):
    """UI-safe account descriptor. NEVER includes the plaintext number."""

    model_config = ConfigDict(frozen=True)

    display_id: str
    nickname: str | None


class SchwabStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    connected: bool
    accounts: list[SchwabAccountSummary] = []
    mkt_data_permission: str | None = None
    last_test_at: datetime | None = None
    last_test_status: str | None = None
    last_test_latency_ms: int | None = None
    last_refreshed_at: datetime | None = None


class SchwabTestErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class SchwabTestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    latency_ms: int | None
    account_count: int | None
    mkt_data_permission: str | None
    error: SchwabTestErrorDetail | None


# --- Helpers --------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    ip = getattr(request.state, "client_ip", None)
    if isinstance(ip, str) and ip:
        return ip
    return request.client.host if request.client else None


def _require_schwab_config(settings: Settings) -> tuple[str, str]:
    """Pull the client id + secret or raise ``SchwabNotConfiguredError``."""
    if not settings.schwab_enabled:
        raise SchwabNotConfiguredError()
    assert settings.schwab_client_id is not None
    assert settings.schwab_client_secret is not None
    return (
        settings.schwab_client_id.get_secret_value(),
        settings.schwab_client_secret.get_secret_value(),
    )


def _encode_state(*, user_id: int, nonce: str, settings: Settings) -> str:
    """Sign a ``state`` JWT with a 10-min TTL, bound to the user + nonce.

    We use ``purpose=schwab_oauth`` so that this token can't be used
    elsewhere in the app — a future code path that inadvertently
    reuses ``JWT_SECRET`` would still reject this state as the wrong
    kind of token.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "purpose": _STATE_PURPOSE,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=_STATE_TTL_SECONDS)).timestamp()),
    }
    token: str = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token


def _decode_state(state: str, settings: Settings) -> tuple[int, str]:
    try:
        raw = jwt.decode(
            state,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise SchwabOAuthStateError() from exc
    if raw.get("purpose") != _STATE_PURPOSE:
        raise SchwabOAuthStateError()
    try:
        user_id = int(str(raw.get("sub", "")))
    except ValueError as exc:
        raise SchwabOAuthStateError() from exc
    nonce = str(raw.get("nonce") or "")
    if not nonce:
        raise SchwabOAuthStateError()
    return user_id, nonce


def _set_state_cookie(response: Response, *, nonce: str, settings: Settings) -> None:
    response.set_cookie(
        key=_STATE_COOKIE_NAME,
        value=nonce,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
        max_age=_STATE_TTL_SECONDS,
        path="/",
    )


def _clear_state_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        _STATE_COOKIE_NAME,
        path="/",
        domain=settings.cookie_domain,
    )


def _frontend_url(settings: Settings, *, schwab: str, reason: str | None = None) -> str:
    """Build the ``/settings?schwab=...`` redirect target."""
    base = settings.frontend_url.rstrip("/")
    params = [("schwab", schwab)]
    if reason:
        params.append(("reason", reason))
    return f"{base}/settings?{urllib.parse.urlencode(params)}"


def _build_account_rows(
    *,
    prefs: UserPreferenceResponse,
    mappings: list[AccountMapping],
) -> list[dict[str, Any]]:
    """Cross-reference ``userPreference.accounts`` with ``/accountNumbers``.

    Produces the encrypted-at-rest list the repository expects:
    ``[{plaintext_acct, hash_value, display_id, nickname}]``. The
    hash lookup is case-insensitive and falls back to empty-string
    when Schwab omits a mapping (rare, but better than raising).
    """
    hash_by_number: dict[str, str] = {m.account_number: m.hash_value for m in mappings}
    rows: list[dict[str, Any]] = []
    for acct in prefs.accounts:
        plain = str(acct.get("accountNumber") or "")
        if not plain:
            continue
        rows.append(
            {
                "plaintext_acct": plain,
                "hash_value": hash_by_number.get(plain, ""),
                "display_id": str(acct.get("displayAcctId") or ""),
                "nickname": (str(acct["nickName"]) if acct.get("nickName") else None),
            }
        )
    return rows


# --- Routes ---------------------------------------------------------------


@router.get(
    "/schwab/start",
    summary="Begin the Schwab OAuth handshake (redirects to Schwab LMS)",
)
@limiter.limit("10/minute")
async def schwab_start(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    client_id, _ = _require_schwab_config(settings)

    nonce = secrets.token_urlsafe(16)
    state = _encode_state(user_id=user_id, nonce=nonce, settings=settings)

    # We return a 302 with the Schwab authorize URL AND drop the nonce
    # cookie. The cookie must be set on the redirect response itself so
    # the browser attaches it on the subsequent callback.
    authorize_url = (
        f"{settings.schwab_oauth_authorize_url}"
        f"?client_id={urllib.parse.quote(client_id, safe='')}"
        f"&redirect_uri={urllib.parse.quote(settings.schwab_redirect_uri, safe='')}"
        f"&state={urllib.parse.quote(state, safe='')}"
    )
    redirect = RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    _set_state_cookie(redirect, nonce=nonce, settings=settings)
    logger.info("schwab_oauth_start", user_id=user_id)
    return redirect


@router.get(
    "/schwab/callback",
    summary="Complete the Schwab OAuth handshake (Schwab-initiated redirect)",
)
async def schwab_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    session: Session = Depends(get_db_session),
    brokers: BrokerCredentialRepository = Depends(get_broker_credential_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> RedirectResponse:
    # Construct a pre-built redirect for the error path so we can clear
    # the cookie in both success and failure arms without repeating
    # boilerplate.
    def _error_redirect(reason: str) -> RedirectResponse:
        target = _frontend_url(settings, schwab="error", reason=reason)
        redir = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
        _clear_state_cookie(redir, settings)
        return redir

    if not code or not state:
        logger.warning("schwab_callback_missing_args")
        return _error_redirect("missing_code_or_state")

    cookie_nonce = request.cookies.get(_STATE_COOKIE_NAME) or ""
    try:
        user_id, jwt_nonce = _decode_state(state, settings)
    except SchwabOAuthStateError:
        logger.warning("schwab_callback_bad_state")
        return _error_redirect("bad_state")
    if not cookie_nonce or not secrets.compare_digest(cookie_nonce, jwt_nonce):
        logger.warning("schwab_callback_nonce_mismatch")
        return _error_redirect("bad_state")

    try:
        client_id, client_secret = _require_schwab_config(settings)
    except SchwabNotConfiguredError:
        return _error_redirect("schwab_not_configured")

    decoded_code = urllib.parse.unquote(code)

    # --- Token exchange --------------------------------------------------
    try:
        tokens = await exchange_code_for_tokens(
            client_id=client_id,
            client_secret=client_secret,
            code=decoded_code,
            redirect_uri=settings.schwab_redirect_uri,
        )
    except SchwabOAuthError as exc:
        logger.warning(
            "schwab_callback_token_exchange_failed",
            user_id=user_id,
            error_code=exc.code,
        )
        return _error_redirect(exc.code)

    # --- Fetch preferences + account numbers in parallel -----------------
    try:
        prefs, mappings = await asyncio.gather(
            get_user_preference(tokens.access_token),
            get_account_numbers(tokens.access_token),
        )
    except SchwabApiError as exc:
        logger.warning(
            "schwab_callback_prefs_fetch_failed",
            user_id=user_id,
            error_code=exc.code,
        )
        return _error_redirect(exc.code)

    # --- Persist refresh token + metadata --------------------------------
    expires_at = datetime.now(UTC) + timedelta(days=7)
    brokers.store_refresh_token(
        user_id=user_id,
        broker="schwab",
        refresh_token=tokens.refresh_token,
        expires_at=expires_at,
    )
    account_rows = _build_account_rows(prefs=prefs, mappings=mappings)
    brokers.store_schwab_metadata(
        user_id,
        streamer_customer_id=prefs.streamer_info.schwab_client_customer_id,
        streamer_correl_id=prefs.streamer_info.schwab_client_correl_id,
        streamer_socket_url=prefs.streamer_info.streamer_socket_url,
        account_hashes=account_rows,
        mkt_data_permission=prefs.mkt_data_permission,
    )
    brokers.touch_last_refreshed(user_id)

    audit.record(
        SCHWAB_CONNECTED,
        user_id=user_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={
            "account_count": len(account_rows),
            "mkt_data_permission": prefs.mkt_data_permission or None,
        },
    )
    logger.info(
        "schwab_connected",
        user_id=user_id,
        account_count=len(account_rows),
    )

    success_url = _frontend_url(settings, schwab="connected")
    redirect = RedirectResponse(url=success_url, status_code=status.HTTP_302_FOUND)
    _clear_state_cookie(redirect, settings)
    return redirect


@router.post(
    "/schwab/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete stored Schwab credential",
)
@limiter.limit("10/minute")
async def schwab_disconnect(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    brokers: BrokerCredentialRepository = Depends(get_broker_credential_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> Response:
    # Always attempt delete — if no row exists, the repository returns
    # False and we still 204 so the frontend doesn't have to special-case
    # "already disconnected".
    brokers.delete(user_id=user_id, broker="schwab")

    # Wipe any cached access token for this user so a pending refresh
    # loop doesn't resurrect stale state.
    clear_cached_access_token(user_id)

    audit.record(
        SCHWAB_DISCONNECTED,
        user_id=user_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    logger.info("schwab_disconnected", user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/schwab/status",
    response_model=SchwabStatusResponse,
    summary="Read Schwab connection state + last probe result",
)
@limiter.limit("60/minute")
async def schwab_status(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    brokers: BrokerCredentialRepository = Depends(get_broker_credential_repository),
    session: Session = Depends(get_db_session),
) -> SchwabStatusResponse:
    # The metadata helper returns None both when the row is missing and
    # when the row exists but hasn't yet completed the metadata step.
    # In either case we report "connected=False" — a half-populated row
    # is functionally equivalent to not connected (the streamer can't
    # work without the preferences).
    metadata = brokers.load_schwab_metadata(user_id)
    # We still need the raw row for last_test_*/last_refreshed_at.
    row = session.execute(
        select(BrokerCredential).where(
            BrokerCredential.user_id == user_id,
            BrokerCredential.broker == "schwab",
        )
    ).scalar_one_or_none()

    if row is None or metadata is None:
        return SchwabStatusResponse(connected=False)

    account_summaries = [
        SchwabAccountSummary(
            display_id=str(acct.get("display_id") or ""),
            nickname=(str(acct["nickname"]) if acct.get("nickname") else None),
        )
        for acct in metadata.accounts
        if isinstance(acct, dict)
    ]

    return SchwabStatusResponse(
        connected=True,
        accounts=account_summaries,
        mkt_data_permission=metadata.mkt_data_permission or None,
        last_test_at=row.last_test_at,
        last_test_status=row.last_test_status,
        last_test_latency_ms=row.last_test_latency_ms,
        last_refreshed_at=row.last_refreshed_at,
    )


@router.post(
    "/schwab/test",
    response_model=SchwabTestResponse,
    summary="Live probe — fetches /userPreference to verify the connection",
)
@limiter.limit("10/minute")
async def schwab_test(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    session: Session = Depends(get_db_session),
    brokers: BrokerCredentialRepository = Depends(get_broker_credential_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> SchwabTestResponse:
    # Build a session factory view for the session-bound refresh helper.
    # The dependency gave us a Session; the helper wants a sessionmaker
    # so it can open its own short-lived session for the refresh call.
    session_factory: sessionmaker[Session] = request.app.state.session_factory

    started = time.monotonic()

    try:
        access_token = await get_or_refresh_access_token(
            user_id=user_id,
            session_factory=session_factory,
            settings=settings,
        )
        prefs = await get_user_preference(access_token)
    except SchwabReauthRequired:
        # The helper already deleted the broken credential row. Audit
        # the event (on the request's DB session, which commits on
        # clean handler return) so the user sees a trail of
        # "disconnected because refresh token expired".
        audit.record(
            SCHWAB_REAUTH_REQUIRED,
            user_id=user_id,
            ip=_client_ip(request),
        )
        return SchwabTestResponse(
            success=False,
            latency_ms=None,
            account_count=None,
            mkt_data_permission=None,
            error=SchwabTestErrorDetail(
                code="reauth_required",
                message="Schwab 連線已失效，請重新連接",
            ),
        )
    except SchwabOAuthError as exc:
        brokers.record_test_result(user_id, status="failed", latency_ms=None)
        logger.warning("schwab_test_oauth_error", user_id=user_id, error_code=exc.code)
        return SchwabTestResponse(
            success=False,
            latency_ms=None,
            account_count=None,
            mkt_data_permission=None,
            error=SchwabTestErrorDetail(code=exc.code, message=_safe_test_message(exc.code)),
        )
    except SchwabApiError as exc:
        measured = int((time.monotonic() - started) * 1000)
        brokers.record_test_result(user_id, status="failed", latency_ms=measured)
        logger.warning("schwab_test_api_error", user_id=user_id, error_code=exc.code)
        return SchwabTestResponse(
            success=False,
            latency_ms=measured,
            account_count=None,
            mkt_data_permission=None,
            error=SchwabTestErrorDetail(code=exc.code, message=_safe_test_message(exc.code)),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    brokers.record_test_result(user_id, status="success", latency_ms=latency_ms)
    logger.info(
        "schwab_test_ok",
        user_id=user_id,
        latency_ms=latency_ms,
        account_count=len(prefs.accounts),
    )
    return SchwabTestResponse(
        success=True,
        latency_ms=latency_ms,
        account_count=len(prefs.accounts),
        mkt_data_permission=prefs.mkt_data_permission or None,
        error=None,
    )


__all__: tuple[str, ...] = ("router",)

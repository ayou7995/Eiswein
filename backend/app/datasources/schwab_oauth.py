"""Schwab OAuth wire layer — stateless HTTP client for token + preference calls.

Strict no-DB boundary
---------------------
Every function in this module takes the credentials / tokens it needs as
arguments and returns immutable dataclasses. The DB / cache / audit log
concerns live one layer up in :mod:`app.services.schwab_session` and in
the broker route handlers.

Why stateless
~~~~~~~~~~~~~
Keeps the unit surface small (easy to mock with a fake ``httpx`` client),
keeps secret material off of module globals, and means the same helper
can serve both the route handler (per-request) and the 20-minute
refresh scheduler (background) without needing to coordinate in-memory
state across call sites.

Error model
~~~~~~~~~~~
* :class:`SchwabOAuthError` — raised by ``exchange_code_for_tokens`` and
  ``refresh_access_token``.
* :class:`SchwabApiError` — raised by ``get_user_preference`` and
  ``get_account_numbers``.

Both carry a stable ``code`` string (``invalid_grant``, ``network_error``,
``server_error``, ``unknown``) so the route handler can map them to a
user-facing ``?schwab=error&reason=...`` query param without parsing
strings. Schwab's documented error envelope (``{message, errors[]}``) is
captured into ``message`` when available.

Retry policy
~~~~~~~~~~~~
``tenacity`` wraps every HTTP call with 3 attempts and exponential
backoff (0.5s → 4s cap). We only retry on transient failures —
``httpx.TimeoutException``, ``httpx.ConnectError``, and HTTP 5xx. 4xx
responses (``invalid_grant``, ``invalid_client``) surface immediately
so the caller doesn't burn Schwab quota on an irrecoverable error.

Logging
~~~~~~~
Tokens and secrets NEVER hit logs. Each successful call emits
``{endpoint, status_code, correl_id, latency_ms}``; failures emit
``{endpoint, error_code}``. The ``Schwab-Client-CorrelId`` response
header is preserved so the operator can trace a support ticket through
Schwab's systems.
"""

from __future__ import annotations

import base64
import time
import urllib.parse
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, cast

import httpx
import structlog
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = structlog.get_logger("eiswein.datasources.schwab_oauth")

_TIMEOUT_SECONDS = 10.0
_CORREL_ID_HEADER = "Schwab-Client-CorrelId"


# --- Public result dataclasses --------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """Schwab ``/oauth/token`` response (both grant types).

    ``id_token`` is present in the wire payload but intentionally
    unused — we don't need the userinfo JWT, and not decoding it keeps
    the jwt library off the hot path.
    """

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    token_type: str
    id_token: str | None = None


@dataclass(frozen=True, slots=True)
class AccountMapping:
    """A single ``/accounts/accountNumbers`` entry.

    ``hash_value`` is what Schwab's ``{accountNumber}`` path param
    expects (Schwab rejects plaintext account numbers in URLs — see
    ``docs/schwab/accounts.md``). ``account_number`` is PII and lives
    in memory only on this dataclass; the repository encrypts it at
    rest.
    """

    account_number: str
    hash_value: str


@dataclass(frozen=True, slots=True)
class StreamerInfo:
    """Streamer connection identifiers from ``/userPreference``.

    The two ``nullable`` fields (``schwab_client_channel``,
    ``schwab_client_function_id``) are populated by Schwab in practice
    but the Swagger declares them as ``string`` without required=true,
    so we carry them as ``str | None`` to avoid crashing on an
    unexpected missing field.
    """

    streamer_socket_url: str
    schwab_client_customer_id: str
    schwab_client_correl_id: str
    schwab_client_channel: str | None
    schwab_client_function_id: str | None


@dataclass(frozen=True, slots=True)
class UserPreferenceResponse:
    """Top-level shape of ``/userPreference``.

    ``accounts`` preserves the raw Schwab shape (dicts) — callers
    cross-reference it with :class:`AccountMapping` entries to build
    the persisted ``[{plaintext_acct, hash_value, display_id,
    nickname}]`` list. Keeping the raw dict keeps this wire layer
    agnostic of the persisted schema.
    """

    accounts: list[dict[str, Any]]
    streamer_info: StreamerInfo
    mkt_data_permission: str


# --- Exceptions -----------------------------------------------------------


class _SchwabErrorBase(Exception):
    """Common fields for both OAuth + API errors.

    Keeps the constructor signature consistent so the route handler
    can ``except (SchwabOAuthError, SchwabApiError) as exc`` and read
    ``exc.code`` / ``exc.http_status`` uniformly.
    """

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status


class SchwabOAuthError(_SchwabErrorBase):
    """Raised by token-endpoint helpers (authcode + refresh grants)."""


class SchwabApiError(_SchwabErrorBase):
    """Raised by /trader/v1 endpoints (userPreference, accountNumbers)."""


# --- Internal helpers -----------------------------------------------------


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _parse_error_envelope(body: dict[str, Any]) -> tuple[str, str]:
    """Pull out ``(error_code, message)`` from common Schwab envelopes.

    OAuth responses use ``{"error": "...", "error_description": "..."}``
    (RFC 6749). API responses use ``{"message": "...", "errors": [...]}``.
    We handle both so the caller never has to re-parse.
    """
    err = body.get("error")
    if isinstance(err, str):
        return err, str(body.get("error_description") or err)
    message_field = body.get("message")
    if isinstance(message_field, str):
        return "api_error", message_field
    return "unknown", "Schwab returned an error without a parseable envelope"


def _normalize_oauth_error(exc: httpx.HTTPStatusError) -> SchwabOAuthError:
    status = exc.response.status_code
    try:
        body = exc.response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        error_code, message = _parse_error_envelope(body)
    else:
        error_code, message = "unknown", str(body)[:200]
    if error_code in {"invalid_grant", "invalid_client", "unauthorized_client"}:
        return SchwabOAuthError(error_code, message, status)
    if status >= 500:
        return SchwabOAuthError("server_error", message, status)
    return SchwabOAuthError(error_code or "unknown", message, status)


def _normalize_api_error(exc: httpx.HTTPStatusError) -> SchwabApiError:
    status = exc.response.status_code
    try:
        body = exc.response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        _, message = _parse_error_envelope(body)
    else:
        message = str(body)[:200]
    if status == 401:
        return SchwabApiError("unauthorized", message, status)
    if status == 403:
        return SchwabApiError("forbidden", message, status)
    if status == 404:
        return SchwabApiError("not_found", message, status)
    if status >= 500:
        return SchwabApiError("server_error", message, status)
    return SchwabApiError("api_error", message, status)


def _is_retryable_status(exc: BaseException) -> bool:
    """Tenacity predicate: only retry on 5xx HTTP responses.

    4xx errors (``invalid_grant``, ``invalid_client``, 404, etc.) are
    surface-once-and-fail — retrying a bad refresh token just wastes
    Schwab quota.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return False


def _retry_transient() -> Any:
    """Build a fresh tenacity decorator for a single call site.

    Re-building each time (rather than one module-level decorator) keeps
    the retry state per-call — no cross-test leakage — and keeps the
    predicate list explicit at the use site.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
        retry=(
            retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError))
            | retry_if_exception(_is_retryable_status)
        ),
    )


def _extract_correl_id(response: httpx.Response) -> str | None:
    return response.headers.get(_CORREL_ID_HEADER)


# --- Public async API -----------------------------------------------------


async def exchange_code_for_tokens(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> TokenResponse:
    """Trade an authorization ``code`` for access + refresh tokens.

    ``code`` may arrive URL-encoded (Schwab's auth-code value contains
    an ``@`` that surfaces as ``%40``). We run ``urllib.parse.unquote``
    here belt-and-suspenders — the route handler also decodes — so the
    function is safe to call with either form. Double-decoding is a
    no-op on a normal ASCII string.
    """
    settings = get_settings()
    decoded_code = urllib.parse.unquote(code)

    data = {
        "grant_type": "authorization_code",
        "code": decoded_code,
        "redirect_uri": redirect_uri,
    }
    return await _post_token(
        url=settings.schwab_oauth_token_url,
        data=data,
        client_id=client_id,
        client_secret=client_secret,
        endpoint_label="oauth.token.authcode",
    )


async def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> TokenResponse:
    """Mint a new access token from a stored refresh token.

    Raises :class:`SchwabOAuthError` with ``code="invalid_grant"`` when
    the refresh token has expired (7-day TTL) or been revoked. The
    caller uses that signal to delete the credential and flag the user
    as "re-auth required".
    """
    settings = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return await _post_token(
        url=settings.schwab_oauth_token_url,
        data=data,
        client_id=client_id,
        client_secret=client_secret,
        endpoint_label="oauth.token.refresh",
    )


async def _post_token(
    *,
    url: str,
    data: dict[str, str],
    client_id: str,
    client_secret: str,
    endpoint_label: str,
) -> TokenResponse:
    headers = {
        "Authorization": _basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async def _do_request() -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, data=data, headers=headers)
            resp.raise_for_status()
            return resp

    wrapped = cast(
        Callable[[], Coroutine[Any, Any, httpx.Response]],
        _retry_transient()(_do_request),
    )
    started = time.monotonic()
    try:
        response = await wrapped()
    except httpx.HTTPStatusError as exc:
        err = _normalize_oauth_error(exc)
        logger.warning(
            "schwab_oauth_error",
            endpoint=endpoint_label,
            error_code=err.code,
            status=err.http_status,
        )
        raise err from exc
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("schwab_oauth_network_error", endpoint=endpoint_label)
        raise SchwabOAuthError("network_error", str(exc)[:200], None) from exc
    except RetryError as exc:  # pragma: no cover — tenacity reraise=True surfaces inner
        logger.warning("schwab_oauth_retry_exhausted", endpoint=endpoint_label)
        raise SchwabOAuthError("network_error", "retry exhausted", None) from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    correl_id = _extract_correl_id(response)
    logger.info(
        "schwab_oauth_ok",
        endpoint=endpoint_label,
        status=response.status_code,
        correl_id=correl_id,
        latency_ms=latency_ms,
    )

    body = response.json()
    try:
        return TokenResponse(
            access_token=str(body["access_token"]),
            refresh_token=str(body["refresh_token"]),
            expires_in=int(body["expires_in"]),
            scope=str(body.get("scope", "api")),
            token_type=str(body.get("token_type", "Bearer")),
            id_token=str(body["id_token"]) if body.get("id_token") else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchwabOAuthError(
            "unknown", "token response missing required fields", response.status_code
        ) from exc


async def get_user_preference(access_token: str) -> UserPreferenceResponse:
    """Fetch streamer identifiers + account metadata + mkt data tier.

    Must be called exactly once post-OAuth and persisted — the Streamer
    (Phase S3) cannot LOGIN without these identifiers. See
    ``docs/schwab/userpreference.md`` for the re-fetch triggers.
    """
    settings = get_settings()
    url = settings.schwab_api_base_url.rstrip("/") + "/userPreference"
    body = await _authenticated_get(access_token=access_token, url=url, label="api.userPreference")
    return _parse_user_preference(body)


async def get_account_numbers(access_token: str) -> list[AccountMapping]:
    """Fetch ``[{accountNumber, hashValue}]`` for each linked account.

    Schwab's Trader API rejects plaintext account numbers in URLs; the
    hash value from this endpoint is the only valid form. We persist
    both so we can map user-friendly display IDs back to API-callable
    hashes.
    """
    settings = get_settings()
    url = settings.schwab_api_base_url.rstrip("/") + "/accounts/accountNumbers"
    body = await _authenticated_get(access_token=access_token, url=url, label="api.accountNumbers")
    if not isinstance(body, list):
        raise SchwabApiError(
            "unknown",
            "accountNumbers response is not a list",
            None,
        )
    return [
        AccountMapping(
            account_number=str(item["accountNumber"]),
            hash_value=str(item["hashValue"]),
        )
        for item in body
        if isinstance(item, dict) and "accountNumber" in item and "hashValue" in item
    ]


async def _authenticated_get(*, access_token: str, url: str, label: str) -> Any:
    headers = {"Authorization": f"Bearer {access_token}"}

    async def _do_request() -> httpx.Response:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp

    wrapped = cast(
        Callable[[], Coroutine[Any, Any, httpx.Response]],
        _retry_transient()(_do_request),
    )
    started = time.monotonic()
    try:
        response = await wrapped()
    except httpx.HTTPStatusError as exc:
        err = _normalize_api_error(exc)
        logger.warning(
            "schwab_api_error",
            endpoint=label,
            error_code=err.code,
            status=err.http_status,
        )
        raise err from exc
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("schwab_api_network_error", endpoint=label)
        raise SchwabApiError("network_error", str(exc)[:200], None) from exc
    except RetryError as exc:  # pragma: no cover
        raise SchwabApiError("network_error", "retry exhausted", None) from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    correl_id = _extract_correl_id(response)
    logger.info(
        "schwab_api_ok",
        endpoint=label,
        status=response.status_code,
        correl_id=correl_id,
        latency_ms=latency_ms,
    )
    return response.json()


def _describe_shape(body: Any) -> dict[str, Any]:
    """Return a minimal, PII-free description of an unknown JSON body.

    Used for diagnostic logging when Schwab's response shape diverges
    from the documented Swagger. We log keys / length / element type —
    NEVER the raw values, which may contain account numbers or IDs.
    """
    if isinstance(body, dict):
        return {"kind": "dict", "keys": sorted(body.keys())}
    if isinstance(body, list):
        first = body[0] if body else None
        first_kind = type(first).__name__
        first_keys = sorted(first.keys()) if isinstance(first, dict) else None
        return {
            "kind": "list",
            "length": len(body),
            "first_type": first_kind,
            "first_keys": first_keys,
        }
    return {"kind": type(body).__name__}


def _parse_user_preference(body: Any) -> UserPreferenceResponse:
    """Turn Schwab's userPreference response into a normalized dataclass.

    Swagger declares the top level as a list, but production sometimes
    returns the doc directly as an object. Accept both shapes.
    """
    if isinstance(body, list):
        if not body:
            logger.warning("schwab_userpref_unexpected_shape", shape=_describe_shape(body))
            raise SchwabApiError("unknown", "userPreference response empty list", None)
        doc = body[0]
    elif isinstance(body, dict):
        doc = body
    else:
        logger.warning("schwab_userpref_unexpected_shape", shape=_describe_shape(body))
        raise SchwabApiError("unknown", "userPreference response shape not recognised", None)

    if not isinstance(doc, dict):
        logger.warning("schwab_userpref_unexpected_shape", shape=_describe_shape(body))
        raise SchwabApiError("unknown", "userPreference element is not an object", None)

    accounts_raw = doc.get("accounts") or []
    if not isinstance(accounts_raw, list):
        logger.warning("schwab_userpref_unexpected_shape", shape=_describe_shape(body))
        raise SchwabApiError("unknown", "userPreference.accounts is not a list", None)
    accounts = [dict(a) for a in accounts_raw if isinstance(a, dict)]

    streamer_raw: dict[str, Any] | None = None
    streamer_field = doc.get("streamerInfo")
    if isinstance(streamer_field, list) and streamer_field and isinstance(streamer_field[0], dict):
        streamer_raw = streamer_field[0]
    elif isinstance(streamer_field, dict):
        streamer_raw = streamer_field

    if streamer_raw is None:
        streamer_info = StreamerInfo(
            streamer_socket_url="",
            schwab_client_customer_id="",
            schwab_client_correl_id="",
            schwab_client_channel=None,
            schwab_client_function_id=None,
        )
    else:
        streamer_info = StreamerInfo(
            streamer_socket_url=str(streamer_raw.get("streamerSocketUrl", "")),
            schwab_client_customer_id=str(streamer_raw.get("schwabClientCustomerId", "")),
            schwab_client_correl_id=str(streamer_raw.get("schwabClientCorrelId", "")),
            schwab_client_channel=_str_or_none(streamer_raw.get("schwabClientChannel")),
            schwab_client_function_id=_str_or_none(streamer_raw.get("schwabClientFunctionId")),
        )

    offers = doc.get("offers") or []
    mkt_data_permission = ""
    if isinstance(offers, list) and offers and isinstance(offers[0], dict):
        mkt_data_permission = str(offers[0].get("mktDataPermission") or "")
    elif isinstance(offers, dict):
        mkt_data_permission = str(offers.get("mktDataPermission") or "")

    return UserPreferenceResponse(
        accounts=accounts,
        streamer_info=streamer_info,
        mkt_data_permission=mkt_data_permission,
    )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__: tuple[str, ...] = (
    "AccountMapping",
    "SchwabApiError",
    "SchwabOAuthError",
    "StreamerInfo",
    "TokenResponse",
    "UserPreferenceResponse",
    "exchange_code_for_tokens",
    "get_account_numbers",
    "get_user_preference",
    "refresh_access_token",
)

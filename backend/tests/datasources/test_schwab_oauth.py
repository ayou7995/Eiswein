"""Tests for app.datasources.schwab_oauth — stateless httpx wire layer.

httpx mocking strategy: monkeypatch httpx.AsyncClient with a callable that
returns a stub client context manager. This avoids the respx dependency (not
in dev deps) while staying close to the real call surface.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.datasources.schwab_oauth import (
    AccountMapping,
    SchwabApiError,
    SchwabOAuthError,
    TokenResponse,
    UserPreferenceResponse,
    exchange_code_for_tokens,
    get_account_numbers,
    get_user_preference,
    refresh_access_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
_API_BASE = "https://api.schwabapi.com/trader/v1"
_CLIENT_ID = "test_client_id"
_CLIENT_SECRET = "test_client_secret"
_REDIRECT_URI = "https://127.0.0.1:8182/api/v1/broker/schwab/callback"

_GOOD_TOKEN_BODY = {
    "access_token": "at_abc123",
    "refresh_token": "rt_xyz789",
    "expires_in": 1800,
    "scope": "api",
    "token_type": "Bearer",
    "id_token": "id_tok_ignored",
}

_USER_PREF_BODY = [
    {
        "accounts": [
            {
                "accountNumber": "11223344",
                "displayAcctId": "...3344",
                "nickName": "Brokerage",
                "accountColor": "Green",
                "primaryAccount": True,
                "type": "BROKERAGE",
                "autoPositionEffect": False,
            }
        ],
        "streamerInfo": [
            {
                "streamerSocketUrl": "wss://streamer-api.schwab.com/ws",
                "schwabClientCustomerId": "cust_id_001",
                "schwabClientCorrelId": "correl_id_001",
                "schwabClientChannel": "IO",
                "schwabClientFunctionId": "APIAPP",
            }
        ],
        "offers": [
            {
                "level2Permissions": True,
                "mktDataPermission": "NP",
            }
        ],
    }
]

_ACCOUNT_NUMBERS_BODY = [
    {"accountNumber": "11223344", "hashValue": "hashed_abc"},
    {"accountNumber": "99887766", "hashValue": "hashed_def"},
]


def _make_response(status: int, body: Any, headers: dict[str, str] | None = None) -> MagicMock:
    """Build a mock httpx.Response with .status_code, .json(), .raise_for_status()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = httpx.Headers(headers or {})
    resp.json.return_value = body
    if status >= 400:
        http_error = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=resp,
        )
        resp.raise_for_status.side_effect = http_error
    else:
        resp.raise_for_status.return_value = None
    return resp


class _FakeAsyncClient:
    """Minimal async context manager that returns pre-configured responses.

    ``responses`` is a list consumed in order — first call returns
    ``responses[0]``, second returns ``responses[1]``, etc. Useful for
    simulating transient failures followed by success.
    """

    def __init__(self, responses: list[MagicMock]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def post(self, url: str, *, data: dict[str, str], headers: dict[str, str]) -> MagicMock:
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        resp = self._responses[self._idx]
        self._idx += 1
        resp.raise_for_status()  # raises if 4xx/5xx
        return resp

    async def get(self, url: str, *, headers: dict[str, str]) -> MagicMock:
        self.get_calls.append({"url": url, "headers": headers})
        resp = self._responses[self._idx]
        self._idx += 1
        resp.raise_for_status()
        return resp


def _patch_client(responses: list[MagicMock]) -> Any:
    """Return a context-manager patch that injects _FakeAsyncClient."""
    fake = _FakeAsyncClient(responses)

    class _FactoryCtx:
        """Replaces ``httpx.AsyncClient(...)`` — returns ``fake`` as the ctx."""

        def __call__(self, **kwargs: Any) -> _FakeAsyncClient:
            return fake

        @property
        def instance(self) -> _FakeAsyncClient:
            return fake

    factory = _FactoryCtx()
    return patch("httpx.AsyncClient", new=factory), factory


# ---------------------------------------------------------------------------
# exchange_code_for_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_happy_path_returns_token_response() -> None:
    resp = _make_response(200, _GOOD_TOKEN_BODY)
    ctx, factory = _patch_client([resp])
    with ctx:
        result = await exchange_code_for_tokens(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            code="auth_code_abc",
            redirect_uri=_REDIRECT_URI,
        )

    assert isinstance(result, TokenResponse)
    assert result.access_token == "at_abc123"
    assert result.refresh_token == "rt_xyz789"
    assert result.expires_in == 1800
    assert result.scope == "api"
    assert result.token_type == "Bearer"
    assert result.id_token == "id_tok_ignored"


@pytest.mark.asyncio
async def test_exchange_code_outgoing_request_has_correct_headers_and_body() -> None:
    resp = _make_response(200, _GOOD_TOKEN_BODY)
    ctx, factory = _patch_client([resp])
    with ctx:
        await exchange_code_for_tokens(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            code="auth_code_abc",
            redirect_uri=_REDIRECT_URI,
        )

    assert len(factory.instance.post_calls) == 1
    call = factory.instance.post_calls[0]

    # URL
    assert call["url"] == _TOKEN_URL

    # Authorization: Basic base64(client_id:client_secret)
    expected_raw = f"{_CLIENT_ID}:{_CLIENT_SECRET}".encode()
    expected_auth = "Basic " + base64.b64encode(expected_raw).decode("ascii")
    assert call["headers"]["Authorization"] == expected_auth

    # Content-Type
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    # Body fields
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "auth_code_abc"
    assert call["data"]["redirect_uri"] == _REDIRECT_URI


@pytest.mark.asyncio
async def test_exchange_code_url_decodes_percent_encoded_code() -> None:
    resp = _make_response(200, _GOOD_TOKEN_BODY)
    ctx, factory = _patch_client([resp])
    with ctx:
        await exchange_code_for_tokens(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            code="abc%40xyz",
            redirect_uri=_REDIRECT_URI,
        )

    call = factory.instance.post_calls[0]
    # %40 → @  (URL-decoded)
    assert call["data"]["code"] == "abc@xyz"


@pytest.mark.asyncio
async def test_exchange_code_invalid_grant_raises_without_retry() -> None:
    error_body = {"error": "invalid_grant", "error_description": "Authorization code expired"}
    resp = _make_response(400, error_body)
    ctx, factory = _patch_client([resp])
    with ctx:
        with pytest.raises(SchwabOAuthError) as exc_info:
            await exchange_code_for_tokens(
                client_id=_CLIENT_ID,
                client_secret=_CLIENT_SECRET,
                code="expired_code",
                redirect_uri=_REDIRECT_URI,
            )

    err = exc_info.value
    assert err.code == "invalid_grant"
    assert err.http_status == 400
    # 4xx → no retry → exactly 1 POST attempt
    assert len(factory.instance.post_calls) == 1


@pytest.mark.asyncio
async def test_exchange_code_three_consecutive_503s_raises_after_three_attempts() -> None:
    # Three server-error responses → retry exhausted → SchwabOAuthError
    error_body = {"message": "Service Unavailable"}
    responses = [_make_response(503, error_body) for _ in range(3)]
    ctx, factory = _patch_client(responses)
    with ctx:
        with pytest.raises(SchwabOAuthError) as exc_info:
            await exchange_code_for_tokens(
                client_id=_CLIENT_ID,
                client_secret=_CLIENT_SECRET,
                code="good_code",
                redirect_uri=_REDIRECT_URI,
            )

    assert exc_info.value.code == "server_error"
    assert len(factory.instance.post_calls) == 3


@pytest.mark.asyncio
async def test_exchange_code_transient_503_then_200_returns_token_response() -> None:
    error_body = {"message": "Transient"}
    responses = [_make_response(503, error_body), _make_response(200, _GOOD_TOKEN_BODY)]
    ctx, factory = _patch_client(responses)
    with ctx:
        result = await exchange_code_for_tokens(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            code="good_code",
            redirect_uri=_REDIRECT_URI,
        )

    assert isinstance(result, TokenResponse)
    assert result.access_token == "at_abc123"
    assert len(factory.instance.post_calls) == 2


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_access_token_happy_path_returns_token_response() -> None:
    new_body = dict(_GOOD_TOKEN_BODY, access_token="new_at", refresh_token="new_rt")
    resp = _make_response(200, new_body)
    ctx, factory = _patch_client([resp])
    with ctx:
        result = await refresh_access_token(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token="stored_rt",
        )

    assert result.access_token == "new_at"
    assert result.refresh_token == "new_rt"
    call = factory.instance.post_calls[0]
    assert call["data"]["grant_type"] == "refresh_token"
    assert call["data"]["refresh_token"] == "stored_rt"


@pytest.mark.asyncio
async def test_refresh_access_token_invalid_grant_raises() -> None:
    error_body = {"error": "invalid_grant", "error_description": "Refresh token expired"}
    resp = _make_response(400, error_body)
    ctx, _ = _patch_client([resp])
    with ctx:
        with pytest.raises(SchwabOAuthError) as exc_info:
            await refresh_access_token(
                client_id=_CLIENT_ID,
                client_secret=_CLIENT_SECRET,
                refresh_token="expired_rt",
            )

    assert exc_info.value.code == "invalid_grant"
    assert exc_info.value.http_status == 400


# ---------------------------------------------------------------------------
# get_user_preference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_preference_happy_path_parses_full_payload() -> None:
    resp = _make_response(200, _USER_PREF_BODY)
    ctx, factory = _patch_client([resp])
    with ctx:
        result = await get_user_preference("access_token_abc")

    assert isinstance(result, UserPreferenceResponse)
    assert len(result.accounts) == 1
    assert result.accounts[0]["accountNumber"] == "11223344"
    assert result.streamer_info.streamer_socket_url == "wss://streamer-api.schwab.com/ws"
    assert result.streamer_info.schwab_client_customer_id == "cust_id_001"
    assert result.streamer_info.schwab_client_correl_id == "correl_id_001"
    assert result.streamer_info.schwab_client_channel == "IO"
    assert result.streamer_info.schwab_client_function_id == "APIAPP"
    assert result.mkt_data_permission == "NP"


@pytest.mark.asyncio
async def test_get_user_preference_uses_bearer_auth_header() -> None:
    resp = _make_response(200, _USER_PREF_BODY)
    ctx, factory = _patch_client([resp])
    with ctx:
        await get_user_preference("my_access_token")

    call = factory.instance.get_calls[0]
    assert call["headers"]["Authorization"] == "Bearer my_access_token"
    assert call["url"].endswith("/userPreference")


@pytest.mark.asyncio
async def test_get_user_preference_401_raises_schwab_api_error_unauthorized() -> None:
    resp = _make_response(401, {"message": "Unauthorized"})
    ctx, _ = _patch_client([resp])
    with ctx:
        with pytest.raises(SchwabApiError) as exc_info:
            await get_user_preference("bad_token")

    assert exc_info.value.code == "unauthorized"
    assert exc_info.value.http_status == 401


# ---------------------------------------------------------------------------
# get_account_numbers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_numbers_happy_path_returns_account_mappings() -> None:
    resp = _make_response(200, _ACCOUNT_NUMBERS_BODY)
    ctx, _ = _patch_client([resp])
    with ctx:
        result = await get_account_numbers("access_token_abc")

    assert len(result) == 2
    assert all(isinstance(m, AccountMapping) for m in result)
    assert result[0].account_number == "11223344"
    assert result[0].hash_value == "hashed_abc"
    assert result[1].account_number == "99887766"
    assert result[1].hash_value == "hashed_def"


@pytest.mark.asyncio
async def test_get_account_numbers_empty_list_returns_empty() -> None:
    resp = _make_response(200, [])
    ctx, _ = _patch_client([resp])
    with ctx:
        result = await get_account_numbers("access_token_abc")

    assert result == []


# ---------------------------------------------------------------------------
# Token values never appear in log output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_token_values_not_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    resp = _make_response(200, _GOOD_TOKEN_BODY)
    ctx, _ = _patch_client([resp])
    with caplog.at_level(logging.DEBUG):
        with ctx:
            await exchange_code_for_tokens(
                client_id=_CLIENT_ID,
                client_secret=_CLIENT_SECRET,
                code="secret_auth_code",
                redirect_uri=_REDIRECT_URI,
            )

    combined_logs = " ".join(caplog.messages)
    # Token values must never appear in log output
    assert "at_abc123" not in combined_logs
    assert "rt_xyz789" not in combined_logs
    assert "id_tok_ignored" not in combined_logs

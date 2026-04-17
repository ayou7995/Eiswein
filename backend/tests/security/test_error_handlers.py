"""Error envelope (B6) tests via direct handler invocation."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security.error_handlers import (
    eiswein_error_handler,
    http_exception_handler,
    register_error_handlers,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.security.exceptions import (
    AccountLockedError,
    ConflictError,
    EisweinError,
    InvalidCredentialsError,
    NotFoundError,
    ValidationError,
)


def _dummy_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (InvalidCredentialsError(), 401, "invalid_password"),
        (AccountLockedError(details={"retry_after_seconds": 60}), 403, "locked_out"),
        (NotFoundError(), 404, "not_found"),
        (ConflictError(), 409, "conflict"),
        (ValidationError(), 422, "validation_error"),
    ],
)
def test_eiswein_error_envelope(exc: EisweinError, status: int, code: str) -> None:
    response = cast(JSONResponse, _run(eiswein_error_handler(_dummy_request(), exc)))
    assert response.status_code == status
    body = response.body.decode("utf-8")
    assert code in body
    assert '"error"' in body


def test_http_exception_envelope() -> None:
    exc = StarletteHTTPException(status_code=403, detail="nope")
    response = cast(JSONResponse, _run(http_exception_handler(_dummy_request(), exc)))
    assert response.status_code == 403
    assert b'"forbidden"' in response.body


def test_unhandled_exception_hides_message() -> None:
    exc = RuntimeError("secret internal traceback")
    response = cast(JSONResponse, _run(unhandled_exception_handler(_dummy_request(), exc)))
    assert response.status_code == 500
    assert b"secret internal traceback" not in response.body
    assert b"internal_error" in response.body


def test_validation_exception_wraps_errors() -> None:
    exc = RequestValidationError(errors=[{"loc": ("body", "x"), "msg": "bad"}])
    response = cast(JSONResponse, _run(validation_exception_handler(_dummy_request(), exc)))
    assert response.status_code == 422
    assert b"validation_error" in response.body


def test_register_error_handlers_attaches_all() -> None:
    app = FastAPI()
    register_error_handlers(app)
    assert EisweinError in app.exception_handlers
    assert StarletteHTTPException in app.exception_handlers
    assert RequestValidationError in app.exception_handlers
    assert Exception in app.exception_handlers

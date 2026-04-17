"""Global FastAPI exception handlers.

Converts every raised exception into the standardized envelope (B6):

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security.exceptions import EisweinError, ValidationError

logger = structlog.get_logger("eiswein.errors")


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def eiswein_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EisweinError)  # noqa: S101 — mypy narrowing
    logger.info(
        "domain_error",
        code=exc.code,
        message=exc.message,
        status=exc.http_status,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=_envelope(exc.code, exc.message, exc.details),
    )


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _http_code_for_status(exc.status_code)
    message = str(exc.detail) if exc.detail else code
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
    )


async def validation_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    err = ValidationError(details={"errors": exc.errors()})
    return JSONResponse(
        status_code=err.http_status,
        content=_envelope(err.code, err.message, err.details),
    )


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=_envelope("internal_error", "伺服器發生錯誤"),
    )


def _http_code_for_status(status: int) -> str:
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
        502: "bad_gateway",
        503: "service_unavailable",
    }
    return mapping.get(status, "http_error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(EisweinError, eiswein_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

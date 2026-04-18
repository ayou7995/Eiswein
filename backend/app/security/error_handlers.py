"""Global FastAPI exception handlers.

Converts every raised exception into the standardized envelope (B6):

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security.exceptions import EisweinError, ValidationError

logger = structlog.get_logger("eiswein.errors")


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def eiswein_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EisweinError)
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
    assert isinstance(exc, StarletteHTTPException)
    code = _http_code_for_status(exc.status_code)
    message = str(exc.detail) if exc.detail else code
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
    )


async def validation_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = sanitize_validation_errors(exc.errors())
    err = ValidationError(details={"errors": errors})
    return JSONResponse(
        status_code=err.http_status,
        content=_envelope(err.code, err.message, err.details),
    )


def sanitize_validation_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Strip non-JSON-serialisable values from Pydantic error dicts.

    Pydantic v2 includes the raw exception object in ``ctx`` when a custom
    field_validator raises — that crashes ``json.dumps``. The docs ``url``
    is also noise for API clients. Keep the useful fields only.
    """
    KEEP = {"loc", "msg", "type", "input"}
    return [{k: v for k, v in e.items() if k in KEEP} for e in errors]


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=_envelope("internal_error", "伺服器發生錯誤"),
    )


async def rate_limit_exceeded_handler(_request: Request, exc: Exception) -> JSONResponse:
    """slowapi hit — standardize to our envelope with a user-friendly message.

    This is the HTTP-layer abuse brake (protects the backend from traffic
    floods); the app-level 5-failures-in-15min IP lockout is the
    credential-protection layer and surfaces a different error code.
    """
    assert isinstance(exc, RateLimitExceeded)
    # exc.detail is like "5 per 1 minute"; not parsed further — the limit
    # string is already exposed via Retry-After in headers when slowapi
    # enables them (headers_enabled=True in build_limiter).
    return JSONResponse(
        status_code=429,
        content=_envelope(
            "rate_limited",
            "請求過於頻繁，請稍後再試",
            {"limit": str(exc.detail) if exc.detail else ""},
        ),
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
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

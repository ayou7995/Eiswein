"""Custom exception hierarchy.

All exceptions serialize through the global handler in `error_handlers.py`
into the standardized error envelope (B6 in docs/STAFF_REVIEW_DECISIONS.md):

    {"error": {"code": "...", "message": "...", "details": {...}}}

`code` is a stable machine string for frontend conditionals; `message` is
user-facing Traditional Chinese; `details` is optional structured data.
"""

from __future__ import annotations

from typing import Any


class EisweinError(Exception):
    """Root exception. Every domain-raised error subclasses this."""

    http_status: int = 500
    code: str = "internal_error"
    message: str = "伺服器發生錯誤"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}


class AuthError(EisweinError):
    http_status = 401
    code = "unauthorized"
    message = "請先登入"


class InvalidCredentialsError(AuthError):
    code = "invalid_password"
    message = "帳號或密碼錯誤"


class AccountLockedError(AuthError):
    http_status = 403
    code = "locked_out"
    message = "登入失敗次數過多，請稍後再試"


class TokenExpiredError(AuthError):
    code = "token_expired"
    message = "登入逾時，請重新登入"


class TokenInvalidError(AuthError):
    code = "token_invalid"
    message = "Token 不合法"


class ValidationError(EisweinError):
    http_status = 422
    code = "validation_error"
    message = "輸入資料不合法"


class NotFoundError(EisweinError):
    http_status = 404
    code = "not_found"
    message = "找不到資源"


class ConflictError(EisweinError):
    http_status = 409
    code = "conflict"
    message = "資源衝突"


class RateLimitedError(EisweinError):
    http_status = 429
    code = "rate_limited"
    message = "請求過於頻繁，請稍後再試"


class DataSourceError(EisweinError):
    http_status = 502
    code = "data_source_error"
    message = "資料來源暫時無法取得"


class IndicatorError(EisweinError):
    http_status = 500
    code = "indicator_error"
    message = "指標計算失敗"


class EncryptionError(EisweinError):
    http_status = 500
    code = "encryption_error"
    message = "加密操作失敗"

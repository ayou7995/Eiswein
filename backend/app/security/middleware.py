"""HTTP middleware stack.

Pipeline order (outermost first):
  1. RequestContextMiddleware — request id, structlog bind, timing
  2. ClientIPMiddleware         — validate CF-Connecting-IP, set state.client_ip
  3. SecurityHeadersMiddleware  — CSP, HSTS, X-Frame-Options, etc.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from ipaddress import IPv4Network, IPv6Network

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.security.cf_ip_validation import cloudflare_networks, is_trusted

logger = structlog.get_logger("eiswein.http")

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach strict security headers to every response (E7)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Resolve `request.state.client_ip` from trusted CF header or peer.

    Also strips `CF-Connecting-IP` if the connecting peer is NOT in a
    trusted Cloudflare range — an attacker directly hitting the backend
    could otherwise inject any value and bypass throttles.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        extra_trusted: Sequence[str] = (),
    ) -> None:
        super().__init__(app)
        v4, v6 = cloudflare_networks(extra_trusted)
        self._v4: list[IPv4Network] = v4
        self._v6: list[IPv6Network] = v6

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        peer = request.client.host if request.client else ""
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip and is_trusted(peer, v4_nets=self._v4, v6_nets=self._v6):
            request.state.client_ip = cf_ip
            request.state.via_cloudflare = True
        else:
            request.state.client_ip = peer
            request.state.via_cloudflare = False
            if cf_ip and peer:
                logger.warning(
                    "untrusted_cf_header",
                    peer=peer,
                    header_value=cf_ip,
                )
        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id + bind structlog context for every request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("request_failed", duration_ms=duration_ms)
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "request_completed",
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response

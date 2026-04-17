"""Rate limiter configuration.

Per E3: keyed by `CF-Connecting-IP` when the request originates from a
trusted Cloudflare IP, otherwise by the transport peer. The middleware
in `middleware.py` handles the trust evaluation; this module exposes a
key function + limiter factory usable by both the app and tests.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_ip_key(request: Request) -> str:
    """Prefer validated `X-Eiswein-Client-IP` (set by CF middleware).

    The middleware puts the validated CF-Connecting-IP (or the transport
    peer if no trusted CF header) at `request.state.client_ip`. If neither
    is available we fall back to the starlette remote address so the
    limiter never crashes on a missing header in dev.
    """
    resolved = getattr(request.state, "client_ip", None)
    if isinstance(resolved, str) and resolved:
        return resolved
    return get_remote_address(request)


def build_limiter(default_limits: list[str] | None = None) -> Limiter:
    return Limiter(
        key_func=client_ip_key,
        default_limits=default_limits or [],
        headers_enabled=True,
    )


# Module-level singleton used by route decorators (@limiter.limit(...)).
# Actual limit enforcement requires SlowAPIMiddleware to be attached to
# the app and `app.state.limiter = limiter` to be set (done in main.py).
# Route decorators just register the limit intent; they take effect when
# the middleware sees the state assignment.
limiter: Limiter = build_limiter()


__all__: tuple[str, ...] = ("build_limiter", "client_ip_key", "limiter")

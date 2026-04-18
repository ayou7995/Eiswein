"""Per-symbol asyncio locks for cold-start concurrency (I4).

Two POSTs to ``/api/v1/watchlist`` for the same ticker in the same
second would otherwise race: both spawn a backfill, both hit yfinance,
and we'd double-insert DailyPrice rows (the UNIQUE(symbol, date)
constraint catches this but only at the cost of wasted bandwidth and
a nasty error in logs).

Module-level singleton dict is intentional — FastAPI runs with
``--workers 1`` so there's exactly one process. APScheduler's
``fcntl.flock`` belt-and-suspenders covers accidental worker count
changes.

Lock lookup is itself synchronized with a tiny async lock so two
requests racing to create the FIRST entry for a symbol both end up
awaiting the same :class:`asyncio.Lock` instance (rule 12:
idempotency).
"""

from __future__ import annotations

import asyncio

_lock_registry: dict[str, asyncio.Lock] = {}
_registry_guard: asyncio.Lock | None = None


def _ensure_registry_guard() -> asyncio.Lock:
    # Lazy init so tests that don't touch the ingestion path don't spin
    # up an event-loop-bound lock at import time.
    global _registry_guard
    if _registry_guard is None:
        _registry_guard = asyncio.Lock()
    return _registry_guard


async def get_symbol_lock(symbol: str) -> asyncio.Lock:
    """Return the :class:`asyncio.Lock` associated with ``symbol``.

    Repeated calls return the same lock instance; concurrent calls for
    the same new symbol serialize on the registry guard and then
    converge on a single lock.
    """
    key = symbol.upper()
    guard = _ensure_registry_guard()
    async with guard:
        lock = _lock_registry.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _lock_registry[key] = lock
        return lock


def reset_locks_for_tests() -> None:
    """Clear the registry. Tests call this between cases."""
    global _registry_guard
    _lock_registry.clear()
    _registry_guard = None

"""Per-symbol and per-user asyncio locks for cold-start concurrency (I4).

Two POSTs to ``/api/v1/watchlist`` for the same ticker in the same
second would otherwise race: both spawn a backfill, both hit yfinance,
and we'd double-insert DailyPrice rows (the UNIQUE(symbol, date)
constraint catches this but only at the cost of wasted bandwidth and
a nasty error in logs).

Module-level singleton dicts are intentional — FastAPI runs with
``--workers 1`` so there's exactly one process. APScheduler's
``fcntl.flock`` belt-and-suspenders covers accidental worker count
changes.

Registry bound: watchlist_max_size (default 100) for the symbol
registry; |users| for the user registry. Neither is evicted on
watchlist removal — restart clears both. Acceptable for single-user
v1; revisit if the cap is raised or multi-user use grows.

Lock lookups are synchronized with a tiny async guard so two requests
racing to create the FIRST entry for a key both end up awaiting the
same :class:`asyncio.Lock` instance (rule 12: idempotency).
"""

from __future__ import annotations

import asyncio

_symbol_registry: dict[str, asyncio.Lock] = {}
_user_registry: dict[int, asyncio.Lock] = {}
_position_registry: dict[int, asyncio.Lock] = {}
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
        lock = _symbol_registry.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _symbol_registry[key] = lock
        return lock


async def get_user_lock(user_id: int) -> asyncio.Lock:
    """Return the :class:`asyncio.Lock` associated with ``user_id``.

    Used to serialize watchlist mutations per user (e.g., cap check +
    insert) so a quick double-POST can't slip past ``watchlist_max_size``.
    """
    guard = _ensure_registry_guard()
    async with guard:
        lock = _user_registry.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_registry[user_id] = lock
        return lock


async def get_position_lock(position_id: int) -> asyncio.Lock:
    """Return the :class:`asyncio.Lock` associated with ``position_id``.

    Serializes concurrent add/reduce/close calls for a single position
    so a race between two /add requests can't double-apply the weighted
    average cost update (read-modify-write on the position row).
    """
    guard = _ensure_registry_guard()
    async with guard:
        lock = _position_registry.get(position_id)
        if lock is None:
            lock = asyncio.Lock()
            _position_registry[position_id] = lock
        return lock


def reset_locks_for_tests() -> None:
    """Clear the registry. Tests call this between cases."""
    global _registry_guard
    _symbol_registry.clear()
    _user_registry.clear()
    _position_registry.clear()
    _registry_guard = None

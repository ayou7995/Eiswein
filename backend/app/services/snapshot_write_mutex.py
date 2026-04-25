"""In-process mutex serializing snapshot-table writers.

``run_daily_update`` and ``BackfillService._run`` both UPSERT into
``market_snapshot`` / ``ticker_snapshot`` / ``daily_signal``. Running
them concurrently risks two writers racing to compute+persist the
same ``(symbol, date)`` tuple — SQLite would serialize the commit but
the compute work is duplicated and, for the market_snapshot row,
ordering matters (the TickerSnapshot's ``market_posture_at_compute``
reads the freshly-written posture).

Project invariant: ``uvicorn --workers 1`` (CLAUDE.md, docker-compose).
All snapshot writers therefore share a single Python process, so
``threading.Lock`` is the right tool. An OS file lock would work too
but carries extra failure modes (stale fds, permission drift, symlink
attacks) that buy nothing in a single-worker design.

If that invariant ever changes — multiple uvicorn workers, an
external CLI that writes snapshots, cross-host deployment — this
module is the single point of change. Swap the Lock for
``fcntl.flock`` or a DB advisory lock; callers don't need to care.
"""

from __future__ import annotations

import threading

# Module-level singleton. Python caches the module after first import,
# so every caller sees the same Lock — that's the whole point. Not
# exposed as a class because there is exactly one of these per
# process; wrapping it in a class invites accidental re-instantiation.
_mutex = threading.Lock()


def snapshot_write_mutex() -> threading.Lock:
    """Return the shared mutex.

    Usage::

        with snapshot_write_mutex():
            ...  # writes to market_snapshot / ticker_snapshot / daily_signal

    Held briefly — only around the sync write + commit section, never
    across an ``await`` (the event loop would stall). The backfill
    runner holds it for its per-day compute loop (~1-5 s/day); the
    live ``daily_update`` holds it just for
    ``_compute_and_compose_for_all`` (~10-30 s for a 3-symbol
    watchlist).
    """
    return _mutex


__all__ = ("snapshot_write_mutex",)

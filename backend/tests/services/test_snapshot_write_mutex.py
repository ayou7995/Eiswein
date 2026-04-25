"""Tests for the snapshot-write in-process mutex.

The mutex is a plain ``threading.Lock`` returned from
:func:`snapshot_write_mutex`. These tests assert the two behaviors that
matter operationally:

* Returns the *same* Lock instance on repeated calls — the module
  singleton guarantee, so daily_update and backfill actually serialize
  against each other rather than each holding a private copy.
* Genuinely serializes concurrent holders — a second thread blocks
  while the first is inside the critical section.
"""

from __future__ import annotations

import threading
import time

from app.services.snapshot_write_mutex import snapshot_write_mutex


def test_mutex_is_module_singleton() -> None:
    """Every call returns the identical Lock object.

    If a future refactor accidentally builds a new Lock per call, the
    serialization guarantee silently breaks — backfill and daily_update
    would each hold their own (different) Lock and proceed in
    parallel.
    """
    assert snapshot_write_mutex() is snapshot_write_mutex()


def test_mutex_serializes_concurrent_holders() -> None:
    """A second thread waits while the first holds the lock.

    We measure the wait by making the first holder sleep briefly and
    checking that the second thread's acquire returns only *after*
    the first has released.
    """
    holder_entered = threading.Event()
    holder_release = threading.Event()
    waiter_entered = threading.Event()
    waiter_entered_at: list[float] = []
    holder_released_at: list[float] = []

    def holder() -> None:
        with snapshot_write_mutex():
            holder_entered.set()
            # Block until the test releases us, so we can observe the
            # waiter thread queueing behind the lock.
            holder_release.wait(timeout=2.0)
            holder_released_at.append(time.monotonic())

    def waiter() -> None:
        holder_entered.wait(timeout=2.0)
        # At this point holder has the lock. Try to acquire — should
        # block until holder releases.
        with snapshot_write_mutex():
            waiter_entered_at.append(time.monotonic())
            waiter_entered.set()

    t_holder = threading.Thread(target=holder)
    t_waiter = threading.Thread(target=waiter)
    t_holder.start()
    t_waiter.start()

    # Give the waiter a window to attempt acquisition; it should not
    # succeed yet.
    assert holder_entered.wait(timeout=1.0)
    assert not waiter_entered.wait(timeout=0.1)

    # Release the holder; waiter should proceed now.
    holder_release.set()
    assert waiter_entered.wait(timeout=1.0)

    t_holder.join(timeout=1.0)
    t_waiter.join(timeout=1.0)
    assert not t_holder.is_alive()
    assert not t_waiter.is_alive()

    # Sanity: the waiter entered after the holder released.
    assert holder_released_at and waiter_entered_at
    assert waiter_entered_at[0] >= holder_released_at[0]

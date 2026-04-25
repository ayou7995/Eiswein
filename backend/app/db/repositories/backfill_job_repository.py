"""BackfillJob repository — orchestrator state + progress counters.

The orchestrator lives outside this module (coming in a later phase).
Here we provide the narrow DB surface it will use:

* create a new row
* fetch the active (pending/running) row — for "refuse to start, one
  already in flight" semantics
* update state transitions
* advance progress counters additively
* set + read the cooperative-cancel flag

All mutations ``flush()`` but never ``commit()`` — caller (the
service or job wrapper) owns the transaction boundary (Phase 0
convention).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BackfillJob

# Last error message is capped so a multi-MB traceback doesn't end up in
# the database — the full trace belongs in structlog.
_ERROR_MAX_LEN = 1000

_TERMINAL_STATES: frozenset[str] = frozenset({"completed", "cancelled", "failed"})
_ACTIVE_STATES: frozenset[str] = frozenset({"pending", "running"})


class BackfillJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        from_date: date,
        to_date: date,
        force: bool,
        user_id: int,
        kind: str = "revalidation",
        symbol: str | None = None,
    ) -> BackfillJob:
        """Insert a new ``pending`` job. Caller is responsible for the
        "is there already an active job?" check via :meth:`get_active`
        — we don't enforce it here so a retry-after-cancellation can
        still create a new row immediately without a DB race window.

        ``kind`` discriminates onboarding vs revalidation. ``symbol``
        is uppercased for consistency with :class:`Watchlist.symbol`;
        revalidation jobs pass ``None``.
        """
        row = BackfillJob(
            kind=kind,
            symbol=symbol.upper() if symbol else None,
            from_date=from_date,
            to_date=to_date,
            state="pending",
            force=force,
            processed_days=0,
            total_days=0,
            skipped_existing_days=0,
            failed_days=0,
            created_by_user_id=user_id,
            cancel_requested=False,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, job_id: int) -> BackfillJob | None:
        stmt = select(BackfillJob).where(BackfillJob.id == job_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active(self) -> BackfillJob | None:
        """The most recent pending-or-running job, or ``None`` if idle.

        Used by revalidation to refuse start while *anything* is in
        flight. Onboardings use :meth:`get_active_for_kind` so they can
        queue behind each other but still defer to revalidation.
        Scans the ``(state, created_at)`` index.
        """
        stmt = (
            select(BackfillJob)
            .where(BackfillJob.state.in_(tuple(_ACTIVE_STATES)))
            .order_by(BackfillJob.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active_for_kind(self, kind: str) -> BackfillJob | None:
        """Most recent pending-or-running job of a specific ``kind``.

        Onboarding's start check passes ``kind='revalidation'`` so two
        onboardings can run concurrently (each in its own thread, all
        serializing at ``snapshot_write_mutex``) but neither starts
        while a revalidation is active.
        """
        stmt = (
            select(BackfillJob)
            .where(
                BackfillJob.state.in_(tuple(_ACTIVE_STATES)),
                BackfillJob.kind == kind,
            )
            .order_by(BackfillJob.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active_onboarding(self, *, user_id: int, symbol: str) -> BackfillJob | None:
        """Active (pending/running) onboarding job for this user+symbol.

        Used by :meth:`DELETE /watchlist/{symbol}` to find the runner
        thread it needs to cooperatively cancel before hard-deleting
        the watchlist row.
        """
        stmt = (
            select(BackfillJob)
            .where(
                BackfillJob.kind == "onboarding",
                BackfillJob.created_by_user_id == user_id,
                BackfillJob.symbol == symbol.upper(),
                BackfillJob.state.in_(tuple(_ACTIVE_STATES)),
            )
            .order_by(BackfillJob.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def update_state(
        self,
        job_id: int,
        state: str,
        error: str | None = None,
    ) -> BackfillJob:
        """Transition to ``state``. Stamps ``started_at`` on the
        pending→running transition and ``finished_at`` on any terminal
        transition. ``error`` is truncated to 1000 chars.
        """
        row = self.get(job_id)
        if row is None:
            msg = f"backfill_job {job_id} not found"
            raise LookupError(msg)

        now = datetime.now(UTC)
        if state == "running" and row.started_at is None:
            row.started_at = now
        if state in _TERMINAL_STATES and row.finished_at is None:
            row.finished_at = now

        row.state = state
        if error is not None:
            row.error = error[:_ERROR_MAX_LEN]
        self._session.flush()
        return row

    def increment_progress(
        self,
        job_id: int,
        *,
        processed: int = 0,
        skipped: int = 0,
        failed: int = 0,
    ) -> BackfillJob:
        """Additive counter bump. All three delta args default to 0 so
        callers name only the counter they're incrementing. Negative
        deltas are rejected — progress never rewinds.
        """
        if processed < 0 or skipped < 0 or failed < 0:
            msg = "increment_progress deltas must be non-negative"
            raise ValueError(msg)
        row = self.get(job_id)
        if row is None:
            msg = f"backfill_job {job_id} not found"
            raise LookupError(msg)
        row.processed_days += processed
        row.skipped_existing_days += skipped
        row.failed_days += failed
        self._session.flush()
        return row

    def request_cancel(self, job_id: int) -> BackfillJob:
        """Flip ``cancel_requested=True``. The orchestrator polls this
        between days and exits cleanly on the next check.
        """
        row = self.get(job_id)
        if row is None:
            msg = f"backfill_job {job_id} not found"
            raise LookupError(msg)
        row.cancel_requested = True
        self._session.flush()
        return row

    def is_cancel_requested(self, job_id: int) -> bool:
        """Cheap scalar read used by the orchestrator's per-day poll.

        Intentionally a single-column SELECT (not ``get`` + attribute
        access) so a loop that runs once per backfill day doesn't hydrate
        the full ORM row on every iteration.
        """
        stmt = select(BackfillJob.cancel_requested).where(BackfillJob.id == job_id)
        result = self._session.execute(stmt).scalar_one_or_none()
        return bool(result)

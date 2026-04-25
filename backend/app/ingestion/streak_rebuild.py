"""Deterministic rebuild of ``market_posture_streak`` after a backfill.

When the backfill orchestrator writes N new ``market_snapshot`` rows,
the ``market_posture_streak`` table is left stale — its rows were
computed for whatever posture sequence existed before the replay. This
module walks ``market_snapshot`` forward and rewrites the streak rows
deterministically so the dashboard badge ("進攻 3 天 ✨") reflects the
now-complete history.

The rebuild is idempotent: calling it twice produces the same streak
rows. Caller owns the transaction boundary (``db.commit()`` happens in
the orchestrator / service, not here), matching the convention used by
every other ingestion module.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.models import MarketPostureStreak, MarketSnapshot

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.streak_rebuild")


def rebuild_streak_table(*, db: Session, from_date: date | None = None) -> int:
    """Rebuild streak rows from ``market_snapshot`` and return rows written.

    Parameters
    ----------
    db
        Session. Caller owns the transaction (no commit here).
    from_date
        When provided, only rebuild rows with ``as_of_date >= from_date``
        and seed the streak state from the row at ``from_date - 1 day``
        (if present). When ``None``, rebuild the entire history from
        scratch.

    Returns
    -------
    int
        The number of streak rows written. Equal to the number of
        ``market_snapshot`` rows in the rebuild window.
    """
    logger.info(
        "rebuild_streak_table_start",
        from_date=from_date.isoformat() if from_date is not None else None,
    )

    # 1. Wipe streak rows in the rebuild window. Everything outside the
    #    window stays authoritative so a partial rebuild is cheap.
    delete_stmt = delete(MarketPostureStreak)
    if from_date is not None:
        delete_stmt = delete_stmt.where(MarketPostureStreak.as_of_date >= from_date)
    db.execute(delete_stmt)

    # 2. Seed prev state from the day BEFORE ``from_date`` so an
    #    incremental rebuild picks up any still-running streak from
    #    outside the window. For a full rebuild (``from_date is None``)
    #    we start fresh.
    prev_posture: str | None = None
    prev_streak_days = 0
    prev_streak_started_on: date | None = None
    if from_date is not None:
        seed = db.execute(
            select(MarketPostureStreak).where(
                MarketPostureStreak.as_of_date == from_date - timedelta(days=1)
            )
        ).scalar_one_or_none()
        if seed is not None:
            prev_posture = seed.current_posture
            prev_streak_days = seed.streak_days
            prev_streak_started_on = seed.streak_started_on

    # 3. Walk market_snapshot forward in the window.
    select_stmt = select(MarketSnapshot).order_by(MarketSnapshot.date.asc())
    if from_date is not None:
        select_stmt = select_stmt.where(MarketSnapshot.date >= from_date)
    snapshots = db.execute(select_stmt).scalars().all()

    now = datetime.now(UTC)
    rows_written = 0
    for snap in snapshots:
        posture = snap.posture
        if posture == prev_posture and prev_streak_started_on is not None:
            streak_days = prev_streak_days + 1
            streak_started_on = prev_streak_started_on
        else:
            streak_days = 1
            streak_started_on = snap.date

        insert_stmt = sqlite_insert(MarketPostureStreak).values(
            as_of_date=snap.date,
            current_posture=posture,
            streak_days=streak_days,
            streak_started_on=streak_started_on,
            computed_at=now,
        )
        # UPSERT so a full-range rebuild overwrites any row that
        # survived the DELETE (e.g. from_date=None path truncates
        # everything; with from_date set, the pre-window rows stay
        # untouched but mid-window rows were already deleted).
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["as_of_date"],
            set_={
                "current_posture": insert_stmt.excluded.current_posture,
                "streak_days": insert_stmt.excluded.streak_days,
                "streak_started_on": insert_stmt.excluded.streak_started_on,
                "computed_at": insert_stmt.excluded.computed_at,
            },
        )
        db.execute(insert_stmt)
        rows_written += 1

        prev_posture = posture
        prev_streak_days = streak_days
        prev_streak_started_on = streak_started_on

    # Final flush so the rows are visible before the caller commits.
    db.flush()

    logger.info(
        "rebuild_streak_table_complete",
        from_date=from_date.isoformat() if from_date is not None else None,
        rows_written=rows_written,
    )
    return rows_written

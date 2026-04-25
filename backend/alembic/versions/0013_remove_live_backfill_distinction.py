"""Drop ``is_backfilled`` columns + revert Watchlist soft-delete to hard-delete.

Revision ID: 0013_remove_live_backfill_distinction
Revises: 0012_backfill_job_table
Create Date: 2026-04-24 00:00:00

Notes
-----
The live-vs-backfilled distinction (added in migration 0010) turned out
to carry no actionable information — with immutable ``daily_price`` and
per-row ``indicator_version`` the two code paths produce identical
numeric results. Likewise the watchlist soft-delete machinery (0011) was
added purely to feed ``symbols_as_of(d)`` for historical replays; the
cleanup flips backfill to "current watchlist" semantics, so soft-delete
becomes pure overhead.

``upgrade()`` order matters:

1. Purge soft-deleted watchlist rows BEFORE restoring the regular
   UNIQUE — otherwise a user who soft-deleted ``SPY`` and re-added it
   (revival branch was live) would briefly hold two rows for the same
   ``(user_id, SPY)`` key and the new constraint would fail to build.
2. Drop ``is_backfilled`` from the three snapshot tables (pure column
   drop; data preserved).
3. On ``watchlist``: drop the partial unique index, drop ``removed_at``,
   recreate the regular ``UniqueConstraint("user_id", "symbol",
   name="uq_watchlist_user_symbol")``.

``downgrade()`` reverses in spirit — re-adds the three columns with
``server_default='0'`` (so the check-constraint / NOT-NULL invariants
hold), re-adds ``removed_at`` nullable, and swaps UNIQUE back to the
partial-on-null form. The ``DELETE`` in ``upgrade`` cannot be reversed
(rows are truly gone) but the user's practical state is unchanged:
soft-deleted rows were already hidden from every read path.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_remove_live_backfill_distinction"
down_revision: Union[str, None] = "0012_backfill_job_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SNAPSHOT_TABLES: tuple[str, ...] = ("market_snapshot", "ticker_snapshot", "daily_signal")


def upgrade() -> None:
    # (1) Purge soft-deleted watchlist rows so the restored UNIQUE on
    # (user_id, symbol) cannot collide with a resurrected tombstone.
    op.execute("DELETE FROM watchlist WHERE removed_at IS NOT NULL")

    # (2) Drop is_backfilled from the three snapshot tables. SQLite
    # ALTER TABLE DROP COLUMN needs the batch copy-and-swap path.
    for table in _SNAPSHOT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("is_backfilled")

    # (3) Watchlist: swap the partial unique index for a regular
    # UniqueConstraint, then drop removed_at.
    op.drop_index("uq_watchlist_user_symbol_active", table_name="watchlist")
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.create_unique_constraint(
            "uq_watchlist_user_symbol", ["user_id", "symbol"]
        )
        batch_op.drop_column("removed_at")


def downgrade() -> None:
    # Reverse step (3): drop regular UNIQUE, re-add removed_at, recreate
    # partial unique index on active rows only.
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.drop_constraint("uq_watchlist_user_symbol", type_="unique")
        batch_op.add_column(
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_index(
        "uq_watchlist_user_symbol_active",
        "watchlist",
        ["user_id", "symbol"],
        unique=True,
        sqlite_where=sa.text("removed_at IS NULL"),
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    # Reverse step (2): re-add the is_backfilled column on every snapshot
    # table, default 0 so existing rows remain valid under NOT NULL.
    for table in reversed(_SNAPSHOT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_backfilled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    # Step (1) cannot be reversed — soft-deleted rows hard-deleted in
    # upgrade() are not recoverable. Intentional; the rows were already
    # invisible to the application before the migration.

"""Watchlist soft-delete (``removed_at``) + partial unique (user_id, symbol).

Revision ID: 0011_watchlist_soft_delete
Revises: 0010_is_backfilled_columns
Create Date: 2026-04-22 00:00:01

Notes
-----
Backfill needs a lookahead-safe "which symbols were on the watchlist on
day D?" query. A hard DELETE erases that history, so we switch Watchlist
to soft-delete: ``removed_at`` is stamped at delete time and all read
paths filter it out.

The existing ``uq_watchlist_user_symbol`` UNIQUE constraint blocks
re-adding a symbol after it's been soft-deleted — which is exactly what
users would expect to be able to do. Same problem ``positions`` solved
in migration 0005 with a partial unique index
``WHERE closed_at IS NULL``. We apply the same pattern here:

* Drop the table-level UNIQUE.
* Add the partial unique index ``WHERE removed_at IS NULL``.

SQLite can't drop a named constraint directly, so we use
``op.batch_alter_table`` which recreates the table under the hood. The
existing row-level ``ix_watchlist_user_symbol`` non-unique index is
preserved — it still serves the ``WHERE user_id = ? AND symbol = ?``
read path.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_watchlist_soft_delete"
down_revision: Union[str, None] = "0010_is_backfilled_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.add_column(
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.drop_constraint("uq_watchlist_user_symbol", type_="unique")

    op.create_index(
        "uq_watchlist_user_symbol_active",
        "watchlist",
        ["user_id", "symbol"],
        unique=True,
        sqlite_where=sa.text("removed_at IS NULL"),
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_watchlist_user_symbol_active", table_name="watchlist")
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.create_unique_constraint(
            "uq_watchlist_user_symbol", ["user_id", "symbol"]
        )
        batch_op.drop_column("removed_at")

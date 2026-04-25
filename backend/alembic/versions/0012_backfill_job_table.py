"""Historical backfill job state table.

Revision ID: 0012_backfill_job_table
Revises: 0011_watchlist_soft_delete
Create Date: 2026-04-22 00:00:02

Notes
-----
Tracks the state of one long-running backfill orchestration. Only ever a
single row in flight at a time — the repository's :meth:`get_active`
guard enforces that application-side by looking for rows in
``state IN ('pending', 'running')``. A composite index on
``(state, created_at)`` makes that scan O(1).

The ``created_by_user_id`` column is a plain integer, NOT a FK. SQLite
foreign key enforcement is opt-in and already disabled for the user
table in practice; adding a constraint here would create a paperwork
mismatch (``batch_alter_table`` rewrites + implicit PRAGMA dance) with
no runtime benefit on the target deployment.

``cancel_requested`` is the cooperative-cancel flag the HTTP
``cancel`` endpoint flips. The orchestrator polls it between trading
days and exits cleanly (state=``cancelled``, ``finished_at`` stamped).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_backfill_job_table"
down_revision: Union[str, None] = "0011_watchlist_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backfill_job",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "force",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "processed_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "skipped_existing_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "failed_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_backfill_job_state_created_at",
        "backfill_job",
        ["state", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_backfill_job_state_created_at", table_name="backfill_job")
    op.drop_table("backfill_job")

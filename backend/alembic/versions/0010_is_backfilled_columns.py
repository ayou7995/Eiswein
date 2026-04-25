"""Add ``is_backfilled`` flag to market_snapshot / ticker_snapshot / daily_signal.

Revision ID: 0010_is_backfilled_columns
Revises: 0009_broker_credential_schwab_fields
Create Date: 2026-04-22 00:00:00

Notes
-----
Backfill orchestrator needs to distinguish rows produced by the live
``daily_update`` path from rows produced by a historical-replay job so
that (a) the UI can render a small icon on reconstructed bars, (b) a
``force=True`` re-backfill can overwrite previously-backfilled rows
without clobbering live-produced ones by default.

``server_default='0'`` lets Alembic mark every existing row as "live" —
no data-migration step required. ``nullable=False`` keeps the invariant
honest going forward. ``op.batch_alter_table`` is required because
SQLite ``ALTER TABLE ... ADD COLUMN`` can't carry a ``NOT NULL`` +
default in one step without the copy-and-swap batch fallback.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_is_backfilled_columns"
down_revision: Union[str, None] = "0009_broker_credential_schwab_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES: tuple[str, ...] = ("market_snapshot", "ticker_snapshot", "daily_signal")


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_backfilled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("is_backfilled")

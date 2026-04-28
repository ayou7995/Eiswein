"""Add ``updated_at`` to ``daily_price`` for partial-bar detection.

Revision ID: 0015_daily_price_updated_at
Revises: 0014_onboarding_and_drift
Create Date: 2026-04-28 00:00:00

Notes
-----
The freshness layer needs to distinguish a partial intra-day bar
(written before NYSE market_close + buffer) from a finalized close so
``run_daily_update`` can self-correct stale rows on the next post-close
run, and the dashboard can surface "盤中即時" vs "已收盤".

SQLite cannot add a NOT NULL column without a default, so we use a
server default of ``CURRENT_TIMESTAMP`` for the upgrade. After the
column exists and existing rows have been backfilled to "now", the
default is dropped — ongoing inserts/UPSERTs use the SQLAlchemy
``default=_utcnow`` / explicit ``set_["updated_at"] = ...`` paths.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_daily_price_updated_at"
down_revision: Union[str, None] = "0014_onboarding_and_drift"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("daily_price") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )

    # Drop the server default so application-level _utcnow() / explicit
    # repository writes are the sole source going forward. SQLite's
    # batch_alter_table copies the table — server_default=None achieves
    # this cleanly.
    with op.batch_alter_table("daily_price") as batch_op:
        batch_op.alter_column("updated_at", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("daily_price") as batch_op:
        batch_op.drop_column("updated_at")

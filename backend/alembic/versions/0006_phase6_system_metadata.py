"""Phase 6 system_metadata key-value table.

Revision ID: 0006_phase6_system_metadata
Revises: 0005_phase5_positions_trades
Create Date: 2026-04-19 12:00:00

Notes
-----
Tiny KV table used by Phase 6 scheduler jobs (``last_daily_update_at``,
``last_backup_at``, ``last_vacuum_at``). String-only values; the
repository handles ISO-8601 serialization for datetimes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase6_system_metadata"
down_revision: Union[str, None] = "0005_phase5_positions_trades"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_metadata",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_metadata")

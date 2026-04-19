"""Phase 2 indicator layer: daily_signal.

Revision ID: 0003_phase2_indicator_layer
Revises: 0002_phase1_data_layer
Create Date: 2026-04-18 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase2_indicator_layer"
down_revision: Union[str, None] = "0002_phase1_data_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_signal",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("indicator_name", sa.String(length=40), nullable=False),
        sa.Column("signal", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("data_sufficient", sa.Boolean(), nullable=False),
        sa.Column("short_label", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("indicator_version", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "symbol", "date", "indicator_name", name="uq_daily_signal_sym_date_ind"
        ),
    )
    op.create_index("ix_daily_signal_symbol", "daily_signal", ["symbol"])
    op.create_index("ix_daily_signal_date", "daily_signal", ["date"])
    op.create_index("ix_daily_signal_symbol_date", "daily_signal", ["symbol", "date"])


def downgrade() -> None:
    op.drop_index("ix_daily_signal_symbol_date", table_name="daily_signal")
    op.drop_index("ix_daily_signal_date", table_name="daily_signal")
    op.drop_index("ix_daily_signal_symbol", table_name="daily_signal")
    op.drop_table("daily_signal")

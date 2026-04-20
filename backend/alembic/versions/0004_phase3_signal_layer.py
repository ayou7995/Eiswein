"""Phase 3 signal layer: ticker_snapshot + market_snapshot + market_posture_streak.

Revision ID: 0004_phase3_signal_layer
Revises: 0003_phase2_indicator_layer
Create Date: 2026-04-18 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase3_signal_layer"
down_revision: Union[str, None] = "0003_phase2_indicator_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("direction_green_count", sa.Integer(), nullable=False),
        sa.Column("direction_red_count", sa.Integer(), nullable=False),
        sa.Column("timing_modifier", sa.String(length=20), nullable=False),
        sa.Column("show_timing_modifier", sa.Boolean(), nullable=False),
        sa.Column("entry_aggressive", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("entry_ideal", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("entry_conservative", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("market_posture_at_compute", sa.String(length=20), nullable=False),
        sa.Column("indicator_version", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "date", name="uq_ticker_snapshot_symbol_date"),
    )
    op.create_index("ix_ticker_snapshot_symbol", "ticker_snapshot", ["symbol"])
    op.create_index("ix_ticker_snapshot_date", "ticker_snapshot", ["date"])
    op.create_index(
        "ix_ticker_snapshot_symbol_date", "ticker_snapshot", ["symbol", "date"]
    )

    op.create_table(
        "market_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.Column("posture", sa.String(length=20), nullable=False),
        sa.Column("regime_green_count", sa.Integer(), nullable=False),
        sa.Column("regime_red_count", sa.Integer(), nullable=False),
        sa.Column("regime_yellow_count", sa.Integer(), nullable=False),
        sa.Column("indicator_version", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_snapshot_date", "market_snapshot", ["date"])

    op.create_table(
        "market_posture_streak",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False, unique=True),
        sa.Column("current_posture", sa.String(length=20), nullable=False),
        sa.Column("streak_days", sa.Integer(), nullable=False),
        sa.Column("streak_started_on", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_posture_streak")
    op.drop_index("ix_market_snapshot_date", table_name="market_snapshot")
    op.drop_table("market_snapshot")
    op.drop_index("ix_ticker_snapshot_symbol_date", table_name="ticker_snapshot")
    op.drop_index("ix_ticker_snapshot_date", table_name="ticker_snapshot")
    op.drop_index("ix_ticker_snapshot_symbol", table_name="ticker_snapshot")
    op.drop_table("ticker_snapshot")

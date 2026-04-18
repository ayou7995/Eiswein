"""Phase 1 data layer: watchlist + daily_price + macro_indicator.

Revision ID: 0002_phase1_data_layer
Revises: 0001_initial_schema
Create Date: 2026-04-18 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase1_data_layer"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column(
            "data_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )
    op.create_index("ix_watchlist_user_id", "watchlist", ["user_id"])
    op.create_index("ix_watchlist_symbol", "watchlist", ["symbol"])
    op.create_index("ix_watchlist_user_symbol", "watchlist", ["user_id", "symbol"])

    op.create_table(
        "daily_price",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("symbol", "date", name="uq_daily_price_symbol_date"),
    )
    op.create_index("ix_daily_price_symbol", "daily_price", ["symbol"])
    op.create_index("ix_daily_price_date", "daily_price", ["date"])
    op.create_index("ix_daily_price_symbol_date", "daily_price", ["symbol", "date"])

    op.create_table(
        "macro_indicator",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("series_id", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.UniqueConstraint("series_id", "date", name="uq_macro_series_date"),
    )
    op.create_index("ix_macro_indicator_series_id", "macro_indicator", ["series_id"])
    op.create_index("ix_macro_indicator_date", "macro_indicator", ["date"])
    op.create_index(
        "ix_macro_indicator_series_date", "macro_indicator", ["series_id", "date"]
    )


def downgrade() -> None:
    op.drop_index("ix_macro_indicator_series_date", table_name="macro_indicator")
    op.drop_index("ix_macro_indicator_date", table_name="macro_indicator")
    op.drop_index("ix_macro_indicator_series_id", table_name="macro_indicator")
    op.drop_table("macro_indicator")
    op.drop_index("ix_daily_price_symbol_date", table_name="daily_price")
    op.drop_index("ix_daily_price_date", table_name="daily_price")
    op.drop_index("ix_daily_price_symbol", table_name="daily_price")
    op.drop_table("daily_price")
    op.drop_index("ix_watchlist_user_symbol", table_name="watchlist")
    op.drop_index("ix_watchlist_symbol", table_name="watchlist")
    op.drop_index("ix_watchlist_user_id", table_name="watchlist")
    op.drop_table("watchlist")

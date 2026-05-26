"""Remove the positions + trades tables.

Revision ID: 0016_remove_positions_trades
Revises: 0015_daily_price_updated_at
Create Date: 2026-04-29 00:00:00

Notes
-----
The 持倉 / trade-log feature has been deleted from the product. This
migration drops the supporting tables (and their indexes) so the schema
matches the ORM. The downgrade re-creates the tables verbatim from
migration 0005 (positions + trades) plus migration 0008 (trade.source /
external_id columns + partial unique index) — kept simple, not elegant.

The drop order is trades-then-positions because trades has an FK into
positions. Index drops use ``if_exists`` so the downgrade-then-upgrade
round-trip is safe even when the original 0005/0008 names diverged in
older deploys.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_remove_positions_trades"
down_revision: Union[str, None] = "0015_daily_price_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- drop trades first (FK trades.position_id -> positions.id) -------
    op.drop_index(
        "uq_trades_source_external_id",
        table_name="trades",
        if_exists=True,
    )
    op.drop_index("ix_trades_user_symbol_executed_at", table_name="trades", if_exists=True)
    op.drop_index("ix_trades_user_executed_at", table_name="trades", if_exists=True)
    op.drop_index("ix_trades_executed_at", table_name="trades", if_exists=True)
    op.drop_index("ix_trades_symbol", table_name="trades", if_exists=True)
    op.drop_index("ix_trades_position_id", table_name="trades", if_exists=True)
    op.drop_index("ix_trades_user_id", table_name="trades", if_exists=True)
    op.drop_table("trades")

    # --- now drop positions ----------------------------------------------
    op.drop_index("uq_positions_user_symbol_open", table_name="positions", if_exists=True)
    op.drop_index("ix_positions_user_closed", table_name="positions", if_exists=True)
    op.drop_index("ix_positions_user_symbol", table_name="positions", if_exists=True)
    op.drop_index("ix_positions_closed_at", table_name="positions", if_exists=True)
    op.drop_index("ix_positions_symbol", table_name="positions", if_exists=True)
    op.drop_index("ix_positions_user_id", table_name="positions", if_exists=True)
    op.drop_table("positions")


def downgrade() -> None:
    # Re-create ``positions`` first because ``trades.position_id`` FK
    # points at it. Schema mirrors migration 0005 verbatim.
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("shares", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("shares >= 0", name="ck_positions_shares_nonneg"),
        sa.CheckConstraint("avg_cost >= 0", name="ck_positions_avg_cost_nonneg"),
    )
    op.create_index("ix_positions_user_id", "positions", ["user_id"])
    op.create_index("ix_positions_symbol", "positions", ["symbol"])
    op.create_index("ix_positions_closed_at", "positions", ["closed_at"])
    op.create_index("ix_positions_user_symbol", "positions", ["user_id", "symbol"])
    op.create_index("ix_positions_user_closed", "positions", ["user_id", "closed_at"])
    op.create_index(
        "uq_positions_user_symbol_open",
        "positions",
        ["user_id", "symbol"],
        unique=True,
        sqlite_where=sa.text("closed_at IS NULL"),
    )

    # ``trades`` schema mirrors migration 0005 plus the 0008 additions
    # (``source`` NOT NULL DEFAULT 'manual', ``external_id`` nullable,
    # and the partial unique on (user_id, source, external_id) WHERE
    # external_id IS NOT NULL). Folded into a single CREATE so a fresh
    # downgrade lands in the post-0008 shape without needing 0008 to
    # also be re-run.
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("shares", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("shares > 0", name="ck_trades_shares_positive"),
        sa.CheckConstraint("price > 0", name="ck_trades_price_positive"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_trades_side_valid"),
    )
    op.create_index("ix_trades_user_id", "trades", ["user_id"])
    op.create_index("ix_trades_position_id", "trades", ["position_id"])
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_executed_at", "trades", ["executed_at"])
    op.create_index("ix_trades_user_executed_at", "trades", ["user_id", "executed_at"])
    op.create_index(
        "ix_trades_user_symbol_executed_at",
        "trades",
        ["user_id", "symbol", "executed_at"],
    )
    op.create_index(
        "uq_trades_source_external_id",
        "trades",
        ["user_id", "source", "external_id"],
        unique=True,
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

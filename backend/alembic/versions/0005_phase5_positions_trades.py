"""Phase 5 positions + trades.

Revision ID: 0005_phase5_positions_trades
Revises: 0004_phase3_signal_layer
Create Date: 2026-04-19 00:00:00

Notes
-----
* ``positions`` gets a PARTIAL unique index on
  ``(user_id, symbol) WHERE closed_at IS NULL``. SQLite supports
  partial indexes natively, but SQLAlchemy's DDL compiler doesn't
  emit the ``WHERE`` clause portably on ``UniqueConstraint``, so we
  drop to ``op.create_index`` with ``sqlite_where=`` (the native
  per-dialect option). Alembic autogenerate would otherwise keep
  trying to "fix" this to a plain unique constraint.
* CHECK constraints are DB-level defense-in-depth (the repository +
  Pydantic both enforce positivity, but a raw ORM misuse should not
  be able to write a nonsense row).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase5_positions_trades"
down_revision: Union[str, None] = "0004_phase3_signal_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    # Partial unique — one open position per (user, symbol). Multiple
    # historical (closed) rows are allowed so re-entries stay
    # distinguishable in the trade log.
    op.create_index(
        "uq_positions_user_symbol_open",
        "positions",
        ["user_id", "symbol"],
        unique=True,
        sqlite_where=sa.text("closed_at IS NULL"),
    )

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


def downgrade() -> None:
    op.drop_index("ix_trades_user_symbol_executed_at", table_name="trades")
    op.drop_index("ix_trades_user_executed_at", table_name="trades")
    op.drop_index("ix_trades_executed_at", table_name="trades")
    op.drop_index("ix_trades_symbol", table_name="trades")
    op.drop_index("ix_trades_position_id", table_name="trades")
    op.drop_index("ix_trades_user_id", table_name="trades")
    op.drop_table("trades")
    op.drop_index("uq_positions_user_symbol_open", table_name="positions")
    op.drop_index("ix_positions_user_closed", table_name="positions")
    op.drop_index("ix_positions_user_symbol", table_name="positions")
    op.drop_index("ix_positions_closed_at", table_name="positions")
    op.drop_index("ix_positions_symbol", table_name="positions")
    op.drop_index("ix_positions_user_id", table_name="positions")
    op.drop_table("positions")

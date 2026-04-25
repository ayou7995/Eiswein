"""Trade.source + Trade.external_id for broker-CSV imports (Phase 5.5).

Revision ID: 0008_trade_source_and_external_id
Revises: 0006_phase6_system_metadata
Create Date: 2026-04-21 00:00:00

Notes
-----
* ``source`` tags a trade row with its provenance (``manual``, ``robinhood``,
  ``moomoo``, ``schwab``). ``server_default='manual'`` backfills existing
  rows so the NOT NULL constraint is satisfiable without a data-migration
  step.
* ``external_id`` holds the broker-supplied (or deterministically-derived)
  trade identifier used for idempotent imports. Nullable — manual rows
  never have one.
* Idempotency is enforced with a PARTIAL UNIQUE index on
  ``(user_id, source, external_id) WHERE external_id IS NOT NULL``. The
  partial predicate keeps the old (user_id, source=manual, external_id
  NULL) rows from colliding. Both ``sqlite_where`` and
  ``postgresql_where`` are set for dialect portability — same pattern as
  the ``uq_positions_user_symbol_open`` index in 0005.
* ``op.batch_alter_table`` is used for the ADD COLUMN operations so the
  column defaults survive SQLite's "recreate the table" fallback path if
  future SQLAlchemy versions enable it — the statements stay correct on
  Postgres too.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_trade_source_and_external_id"
down_revision: Union[str, None] = "0006_phase6_system_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default="manual",
            )
        )
        batch_op.add_column(
            sa.Column("external_id", sa.String(length=128), nullable=True),
        )
    op.create_index(
        "uq_trades_source_external_id",
        "trades",
        ["user_id", "source", "external_id"],
        unique=True,
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_trades_source_external_id", table_name="trades")
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_column("external_id")
        batch_op.drop_column("source")

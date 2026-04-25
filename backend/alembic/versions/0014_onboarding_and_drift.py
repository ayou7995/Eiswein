"""Onboarding job kind + per-symbol symbol column + SPY seed.

Revision ID: 0014_onboarding_and_drift
Revises: 0013_remove_live_backfill_distinction
Create Date: 2026-04-22 00:00:00

Notes
-----
Phase-1 UX overhaul: "backfill" is no longer a user concept. Two kinds
of job now live on the same :class:`BackfillJob` table:

* ``kind='onboarding'`` — one watchlist symbol's cold-start price fetch
  plus gap-fill of ticker_snapshot rows for every existing
  market_snapshot date. ``symbol`` is NOT NULL for these rows.
* ``kind='revalidation'`` — a full historical replay triggered when
  :data:`INDICATOR_VERSION` drifts past persisted rows. ``symbol`` is
  NULL. ``from_date`` / ``to_date`` carry the range (oldest stored
  market_snapshot date to today).

Existing rows (the legacy unnamed "backfill" operation) all predate
this migration and are functionally revalidation jobs — the
``server_default='revalidation'`` on ``kind`` handles that case.

``symbol`` is a nullable VARCHAR(16) — UPPER-cased on write by the
service layer, matching the watchlist table's shape. No FK: the column
is an informational pointer, not a referential constraint (watchlist
rows can be deleted while a job is mid-run; the pointer stays so
logs/UI can still render the symbol).

SPY seed
--------
SPY is the system benchmark: it drives the A/D Day Count +
relative-strength macro indicators, and the onboarding gap-fill needs
market_snapshot rows to exist for every historical date. The seed
inserts SPY into the **lowest user_id's** watchlist (the single admin
user under the v1 deployment) with ``data_status='pending'`` so the
next daily_update or the explicit onboarding runner fills prices.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_onboarding_and_drift"
down_revision: Union[str, None] = "0013_remove_live_backfill_distinction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (1) Add kind + symbol columns to backfill_job. SQLite ALTER TABLE
    # cannot add a NOT NULL column without a default, so we give kind a
    # server default of 'revalidation' — existing rows are historical
    # backfill jobs that are now classified as revalidations.
    with op.batch_alter_table("backfill_job") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'revalidation'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "symbol",
                sa.String(length=16),
                nullable=True,
            )
        )

    # (2) Seed SPY into the admin user's watchlist if not already present.
    # INSERT ... WHERE NOT EXISTS is portable between SQLite and Postgres.
    # The lowest user id is the admin in v1; if no users exist yet
    # (fresh install — main.py seeds the admin at lifespan start), the
    # subquery returns no rows and the insert is a no-op.
    op.execute(
        """
        INSERT INTO watchlist (user_id, symbol, data_status, added_at)
        SELECT u.id, 'SPY', 'pending', CURRENT_TIMESTAMP
          FROM users u
         WHERE u.id = (SELECT MIN(id) FROM users)
           AND NOT EXISTS (
               SELECT 1 FROM watchlist w
                WHERE w.user_id = u.id
                  AND w.symbol = 'SPY'
           )
        """
    )


def downgrade() -> None:
    # Reverse only the schema columns. The SPY seed row is data, not
    # structural — leave it in place (a user could've been curating
    # their watchlist since the migration ran; removing their SPY
    # selection on downgrade would be surprising).
    with op.batch_alter_table("backfill_job") as batch_op:
        batch_op.drop_column("symbol")
        batch_op.drop_column("kind")

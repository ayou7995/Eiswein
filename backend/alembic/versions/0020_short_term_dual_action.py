"""Dual mid + short term action columns on snapshots (v2 Phase 1).

Revision ID: 0020_short_term_dual_action
Revises: 0019_calendar_event
Create Date: 2026-06-05 22:00:00

Notes
-----
Adds 3 columns to ``ticker_snapshot`` and 3 columns to ``market_snapshot``
to hold a short-term verdict alongside the existing mid-term verdict.
Each ticker now carries ``action_short`` + counts; the market also
carries ``posture_short`` + counts. UI renders the two in a dual badge
so the operator can tell a 3-5 day tactical signal apart from a 2-4
week holding decision.

Back-fill strategy
------------------
New columns are NOT NULL. For rows that existed before this migration
(written by the v1 single-action ingestion):

* ``action_short`` defaults to ``"watch"`` — the "data insufficient"
  fallback the short classifier uses anyway. Safer than copying the
  mid-term ``action`` over (would create a misleading "they agree"
  illusion when in reality short was never computed).
* counts default to ``0`` — matches the WATCH fallback semantics.
* ``posture_short`` defaults to ``"normal"`` — mirror of mid-term's
  conservative fallback.

After the next ``daily_update`` run, every active row gets re-composed
with real short-term values via UPSERT.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0020_short_term_dual_action"
down_revision = "0019_calendar_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ticker_snapshot — 3 new columns
    with op.batch_alter_table("ticker_snapshot") as batch:
        batch.add_column(
            sa_column_str(
                "action_short", default="watch", length=20
            )
        )
        batch.add_column(
            sa_column_int("direction_short_green_count", default=0)
        )
        batch.add_column(
            sa_column_int("direction_short_red_count", default=0)
        )

    # market_snapshot — 3 new columns
    with op.batch_alter_table("market_snapshot") as batch:
        batch.add_column(
            sa_column_str(
                "posture_short", default="normal", length=20
            )
        )
        batch.add_column(
            sa_column_int("regime_short_green_count", default=0)
        )
        batch.add_column(
            sa_column_int("regime_short_red_count", default=0)
        )


def downgrade() -> None:
    with op.batch_alter_table("ticker_snapshot") as batch:
        batch.drop_column("direction_short_red_count")
        batch.drop_column("direction_short_green_count")
        batch.drop_column("action_short")

    with op.batch_alter_table("market_snapshot") as batch:
        batch.drop_column("regime_short_red_count")
        batch.drop_column("regime_short_green_count")
        batch.drop_column("posture_short")


def sa_column_str(name: str, *, default: str, length: int) -> object:
    """SQLAlchemy String column factory with a server-side default so
    the NOT NULL constraint doesn't trip on existing rows."""
    import sqlalchemy as sa

    return sa.Column(
        name,
        sa.String(length=length),
        nullable=False,
        server_default=default,
    )


def sa_column_int(name: str, *, default: int) -> object:
    import sqlalchemy as sa

    return sa.Column(
        name,
        sa.Integer(),
        nullable=False,
        server_default=str(default),
    )

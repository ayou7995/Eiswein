"""Add data_as_of to daily_signal (data-provenance honesty).

Revision ID: 0021_daily_signal_data_as_of
Revises: 0020_short_term_dual_action
Create Date: 2026-06-06 09:00:00

Why
----
Before this column, indicator results silently attributed their input
data's date to the snapshot's ``date`` column. When FRED publishes
VIXCLS one day late, the system computed VIX using yesterday's value
and stored it as if it were today's reading. Same for any cross-source
indicator whose worst-lagged input had stale data.

``data_as_of`` is the actual date of the underlying data the indicator
consumed (max of the last index of every input frame, or min for
multi-source consumers). When ``data_as_of < date``, the UI surfaces a
"資料截至 X" pill so the operator can see at a glance that today's
snapshot is computed from older inputs.

Back-fill strategy
------------------
Historical rows can't be told apart from "fresh on the day they were
computed" — we don't have FRED's then-current state. Conservative
choice: back-fill ``data_as_of = date`` so existing rows render as
"fresh". Going forward every new row carries the honest value.

Nullable column so a) the migration is non-destructive and b) future
fallback paths (insufficient_result / error_result) that don't know
the input date can write NULL without lying.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_daily_signal_data_as_of"
down_revision = "0020_short_term_dual_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("daily_signal") as batch:
        batch.add_column(sa.Column("data_as_of", sa.Date(), nullable=True))

    # Conservative back-fill: pre-existing rows set data_as_of = date so
    # the freshness check (data_as_of < date) returns False for them —
    # they render as "fresh". We can't recover FRED's then-current state.
    op.execute("UPDATE daily_signal SET data_as_of = date WHERE data_as_of IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("daily_signal") as batch:
        batch.drop_column("data_as_of")

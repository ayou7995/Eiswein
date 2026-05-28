"""Calendar events table for Catalyst Calendar v1.

Revision ID: 0019_calendar_event
Revises: 0018_keep_only_watching_default_group
Create Date: 2026-05-27 21:00:00

Notes
-----
Single table holding three event flavours discriminated by ``type``:

* ``earnings`` — per-ticker quarterly earnings; ``ticker_symbol`` set,
  ``payload_json`` may contain consensus EPS, time-of-day (BMO/AMC).
* ``macro`` — US economic releases (CPI, PCE, PPI, NFP, FOMC, PMI);
  ``ticker_symbol`` NULL, ``payload_json`` may carry prior reading.
* ``industry`` — sector / conference / IPO catalysts (WWDC, GTC, ASML
  legal day); ``ticker_symbol`` set only when the event ties to a
  single ticker, else NULL.

The natural dedup key is ``(event_date, type, ticker_symbol, title)``,
but SQLite UNIQUE treats NULL as distinct — two macro events with the
same date + title would not collide. A functional UNIQUE index that
coalesces NULL ``ticker_symbol`` to '' restores the intended semantics
so the daily sync is idempotent (re-running 5x produces no duplicates).

``payload_json`` is a JSON column so per-type metadata can evolve
without further migrations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_calendar_event"
down_revision: str | None = "0018_keep_only_watching_default_group"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        # event_time stored as Text "HH:MM ET" or "AMC" / "BMO" markers
        # rather than TIME — the wall-clock string is what we display,
        # and TIME columns lose the BMO/AMC distinction.
        sa.Column("event_time", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=10), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "type IN ('earnings', 'macro', 'industry')",
            name="ck_calendar_event_type",
        ),
    )
    # Range queries (start ≤ event_date ≤ end) dominate; index on date.
    op.create_index(
        "ix_calendar_event_date_type",
        "calendar_event",
        ["event_date", "type"],
    )
    # Per-ticker lookup for the TickerDetail "next catalyst" chip.
    op.create_index(
        "ix_calendar_event_ticker",
        "calendar_event",
        ["ticker_symbol", "event_date"],
    )
    # Functional UNIQUE: coalesce NULL ticker to empty string so macro
    # events with same date + title de-dup correctly. Sync job upsert
    # relies on this.
    op.create_index(
        "uq_calendar_event_dedup",
        "calendar_event",
        [
            "event_date",
            "type",
            sa.text("COALESCE(ticker_symbol, '')"),
            "title",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_calendar_event_dedup", table_name="calendar_event")
    op.drop_index("ix_calendar_event_ticker", table_name="calendar_event")
    op.drop_index("ix_calendar_event_date_type", table_name="calendar_event")
    op.drop_table("calendar_event")

"""Drop the unused default groups (Core holdings / Speculative / Macro / ETF).

Revision ID: 0018_keep_only_watching_default_group
Revises: 0017_watchlist_groups_tags
Create Date: 2026-05-26 00:00:00

Notes
-----
Migration 0017 seeded four default groups per user as a starter taxonomy.
In practice the operator only uses ``Watching`` and prefers to create the
other buckets manually as needed. This migration removes the three
extras — but ONLY when they are still empty, so a user who has already
populated one of those names doesn't lose data.

Safety: idempotent. If the groups were already deleted (or renamed),
the DELETE simply matches zero rows. The ``group_id IS NULL`` clause on
the inner SELECT confirms nothing depends on the row before we drop it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_keep_only_watching_default_group"
down_revision: str | None = "0017_watchlist_groups_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REMOVABLE_NAMES = ("Core holdings", "Speculative", "Macro / ETF")


def upgrade() -> None:
    # Delete each empty default group. Inline the names rather than a
    # parameterised loop because op.execute() doesn't bind dialect params
    # uniformly across SQLite + Postgres without raw connection access.
    # Names are a fixed tuple of internal seed identifiers (no user
    # input), so the f-string interpolation is safe — bandit S608 is a
    # false positive here.
    for name in _REMOVABLE_NAMES:
        op.execute(
            f"""
            DELETE FROM watchlist_group
             WHERE name = '{name}'
               AND id NOT IN (SELECT DISTINCT group_id FROM watchlist
                              WHERE group_id IS NOT NULL)
            """  # noqa: S608
        )


def downgrade() -> None:
    # Re-seed the three default groups for every user that still has the
    # ``Watching`` group (the only one 0017 guarantees). Positions are
    # assigned 0/2/3 so ``Watching`` (pos 1) keeps its original slot.
    op.execute(
        """
        INSERT INTO watchlist_group (user_id, name, position, created_at)
        SELECT DISTINCT w.user_id, 'Core holdings', 0, CURRENT_TIMESTAMP
          FROM watchlist_group w
         WHERE w.name = 'Watching'
           AND NOT EXISTS (
               SELECT 1 FROM watchlist_group g
                WHERE g.user_id = w.user_id AND g.name = 'Core holdings'
           )
        """
    )
    op.execute(
        """
        INSERT INTO watchlist_group (user_id, name, position, created_at)
        SELECT DISTINCT w.user_id, 'Speculative', 2, CURRENT_TIMESTAMP
          FROM watchlist_group w
         WHERE w.name = 'Watching'
           AND NOT EXISTS (
               SELECT 1 FROM watchlist_group g
                WHERE g.user_id = w.user_id AND g.name = 'Speculative'
           )
        """
    )
    op.execute(
        """
        INSERT INTO watchlist_group (user_id, name, position, created_at)
        SELECT DISTINCT w.user_id, 'Macro / ETF', 3, CURRENT_TIMESTAMP
          FROM watchlist_group w
         WHERE w.name = 'Watching'
           AND NOT EXISTS (
               SELECT 1 FROM watchlist_group g
                WHERE g.user_id = w.user_id AND g.name = 'Macro / ETF'
           )
        """
    )

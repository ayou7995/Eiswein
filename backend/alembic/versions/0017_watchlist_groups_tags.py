"""Watchlist groups + tags + symbol_tag join table.

Revision ID: 0017_watchlist_groups_tags
Revises: 0016_remove_positions_trades
Create Date: 2026-04-29 12:00:00

Notes
-----
Three new tables plus a nullable ``group_id`` column on ``watchlist``.

* ``watchlist_group`` — folder-like grouping. ``UNIQUE(user_id, name COLLATE NOCASE)``
  + ``position`` so the sidebar can render groups in user-controlled order.
* ``watchlist_tag`` — multi-tag labels. Color is locked to a 6-digit hex
  via CHECK constraint so SQLite rejects ``#fff`` / ``red`` / etc. at the
  DB level (defence in depth — repository validates too).
* ``watchlist_symbol_tag`` — many-to-many join. CASCADE on both FKs so
  deleting a watchlist row or a tag automatically purges attachments.

``watchlist.group_id`` is added via ``batch_alter_table`` because SQLite
cannot ``ALTER TABLE ADD COLUMN`` with a foreign key constraint in one
shot. ``ON DELETE SET NULL`` means deleting a group orphans its members
to "unassigned" rather than nuking the watchlist entries.

Seed step
---------
Every existing user gets four default groups (``Core holdings`` /
``Watching`` / ``Speculative`` / ``Macro / ETF``) at positions 0-3. Every
existing watchlist row gets reassigned to that user's ``Watching`` group
so the sidebar has something coherent to render on first paint.

Both seed statements use ``INSERT INTO ... SELECT FROM`` so they work
identically on SQLite and Postgres.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_watchlist_groups_tags"
down_revision: Union[str, None] = "0016_remove_positions_trades"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_GROUPS: tuple[tuple[int, str], ...] = (
    (0, "Core holdings"),
    (1, "Watching"),
    (2, "Speculative"),
    (3, "Macro / ETF"),
)
_DEFAULT_GROUP_FOR_EXISTING_SYMBOLS = "Watching"


def upgrade() -> None:
    # (1) watchlist_group --------------------------------------------------
    op.create_table(
        "watchlist_group",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "name",
            name="uq_watchlist_group_user_name",
            # SQLite honors COLLATE on the column; the index expression
            # below pins the case-insensitive semantics regardless of the
            # column collation.
        ),
    )
    # Case-insensitive uniqueness via a functional index — SQLite's
    # UNIQUE constraint above is byte-exact, but the functional index
    # blocks a second "WATCHING" when "Watching" exists. The repository
    # layer also checks via case-insensitive comparison; both layers are
    # honoured for defence in depth.
    op.create_index(
        "uq_watchlist_group_user_lower_name",
        "watchlist_group",
        ["user_id", sa.text("LOWER(name)")],
        unique=True,
    )
    op.create_index(
        "ix_watchlist_group_user",
        "watchlist_group",
        ["user_id", "position"],
    )

    # (2) watchlist_tag ----------------------------------------------------
    op.create_table(
        "watchlist_tag",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("color", sa.CHAR(length=7), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "color GLOB '#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]"
            "[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'",
            name="ck_watchlist_tag_color_hex",
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlist_tag_user_name"),
    )
    op.create_index(
        "uq_watchlist_tag_user_lower_name",
        "watchlist_tag",
        ["user_id", sa.text("LOWER(name)")],
        unique=True,
    )
    op.create_index(
        "ix_watchlist_tag_user",
        "watchlist_tag",
        ["user_id"],
    )

    # (3) watchlist_symbol_tag (join table) -------------------------------
    op.create_table(
        "watchlist_symbol_tag",
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlist.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("watchlist_tag.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.create_index(
        "ix_watchlist_symbol_tag_tag",
        "watchlist_symbol_tag",
        ["tag_id"],
    )

    # (4) watchlist.group_id column ---------------------------------------
    # batch_alter_table copies the table — every constraint must carry a
    # name so alembic can render the CREATE TABLE replacement. Use an
    # explicit FK + naming convention.
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.add_column(
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey(
                    "watchlist_group.id",
                    ondelete="SET NULL",
                    name="fk_watchlist_group_id",
                ),
                nullable=True,
            )
        )

    # (5) Seed default groups per existing user ---------------------------
    # ``INSERT ... SELECT FROM users`` works the same on SQLite + Postgres.
    # Skip if a group of the same name already exists (idempotent for any
    # re-run / partially-applied state).
    for position, name in _DEFAULT_GROUPS:
        op.execute(
            sa.text(
                """
                INSERT INTO watchlist_group (user_id, name, position, created_at)
                SELECT u.id, :name, :position, CURRENT_TIMESTAMP
                  FROM users u
                 WHERE NOT EXISTS (
                       SELECT 1 FROM watchlist_group g
                        WHERE g.user_id = u.id
                          AND LOWER(g.name) = LOWER(:name)
                   )
                """
            ).bindparams(name=name, position=position)
        )

    # (6) Assign existing watchlist rows to the user's ``Watching`` group --
    op.execute(
        sa.text(
            """
            UPDATE watchlist
               SET group_id = (
                       SELECT g.id
                         FROM watchlist_group g
                        WHERE g.user_id = watchlist.user_id
                          AND LOWER(g.name) = LOWER(:name)
                        LIMIT 1
                   )
             WHERE group_id IS NULL
            """
        ).bindparams(name=_DEFAULT_GROUP_FOR_EXISTING_SYMBOLS)
    )


def downgrade() -> None:
    # Drop in reverse FK order: column on watchlist first (it references
    # watchlist_group), then the join table (it references watchlist +
    # watchlist_tag), then the two top-level tables.
    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.drop_column("group_id")

    op.drop_index("ix_watchlist_symbol_tag_tag", table_name="watchlist_symbol_tag")
    op.drop_table("watchlist_symbol_tag")

    op.drop_index("ix_watchlist_tag_user", table_name="watchlist_tag")
    op.drop_index("uq_watchlist_tag_user_lower_name", table_name="watchlist_tag")
    op.drop_table("watchlist_tag")

    op.drop_index("ix_watchlist_group_user", table_name="watchlist_group")
    op.drop_index("uq_watchlist_group_user_lower_name", table_name="watchlist_group")
    op.drop_table("watchlist_group")

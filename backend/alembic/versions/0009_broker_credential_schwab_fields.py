"""BrokerCredential Schwab-specific fields (Workstream A).

Revision ID: 0009_broker_credential_schwab_fields
Revises: 0008_trade_source_and_external_id
Create Date: 2026-04-21 12:00:00

Notes
-----
Adds Schwab-specific metadata columns to ``broker_credentials`` so that
the post-OAuth "user preferences" payload (streamer customer id, streamer
correlation id, account hashes, market data permission) can be persisted
alongside the refresh token, plus a health-check triple for the
scheduled token-refresh / broker-test jobs.

Design decisions
~~~~~~~~~~~~~~~~
* Three new encrypted blobs, each with its own ``nonce`` + ``tag`` pair.
  AES-GCM demands a fresh nonce per ciphertext so we can't piggy-back on
  ``token_nonce`` / ``token_tag``.
* ``streamer_socket_url`` is plain text — Schwab publishes this URL,
  it's not a secret, and encrypting it would make debugging harder.
* All new columns are nullable so existing rows (none of which have
  Schwab metadata yet) stay valid — no backfill needed.
* ``op.batch_alter_table`` is required for ADD COLUMN on SQLite when a
  future change wants column defaults; using it here keeps the pattern
  consistent with migration 0008.
* No new indexes — these fields are always looked up by (user_id, broker)
  which is already indexed via ``uq_broker_credentials_user_broker``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_broker_credential_schwab_fields"
down_revision: Union[str, None] = "0008_trade_source_and_external_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("broker_credentials") as batch_op:
        batch_op.add_column(
            sa.Column("encrypted_streamer_customer_id", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("streamer_customer_id_nonce", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("streamer_customer_id_tag", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("encrypted_streamer_correl_id", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("streamer_correl_id_nonce", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("streamer_correl_id_tag", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("encrypted_account_hashes", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("account_hashes_nonce", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("account_hashes_tag", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("streamer_socket_url", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("mkt_data_permission", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_test_status", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_test_latency_ms", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("broker_credentials") as batch_op:
        batch_op.drop_column("last_test_latency_ms")
        batch_op.drop_column("last_test_status")
        batch_op.drop_column("last_test_at")
        batch_op.drop_column("mkt_data_permission")
        batch_op.drop_column("streamer_socket_url")
        batch_op.drop_column("account_hashes_tag")
        batch_op.drop_column("account_hashes_nonce")
        batch_op.drop_column("encrypted_account_hashes")
        batch_op.drop_column("streamer_correl_id_tag")
        batch_op.drop_column("streamer_correl_id_nonce")
        batch_op.drop_column("encrypted_streamer_correl_id")
        batch_op.drop_column("streamer_customer_id_tag")
        batch_op.drop_column("streamer_customer_id_nonce")
        batch_op.drop_column("encrypted_streamer_customer_id")

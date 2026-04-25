"""BrokerCredential encrypted storage access.

Ciphertext and key never cross this boundary together — callers pass
plaintext or receive plaintext via the `store` / `load` helpers.

Schwab metadata (streamer ids, account hashes, permission, socket URL)
is added by Workstream A: each secret field lives in its own
``(ciphertext, nonce, tag)`` triple because AES-GCM forbids nonce
reuse. The non-secret ``streamer_socket_url`` is stored plain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BrokerCredential
from app.security.encryption import CipherBundle, decrypt, encrypt


@dataclass(frozen=True, slots=True)
class SchwabMetadata:
    """Decrypted Schwab-specific metadata bundle.

    Fields mirror the encrypted columns added in migration 0009.
    ``accounts`` is the JSON-decoded list originally passed in as
    ``account_hashes`` — each entry is expected to be a dict with
    ``plaintext_acct``, ``hash_value``, ``display_id`` but the shape is
    opaque to this repository (callers define it).
    """

    streamer_customer_id: str
    streamer_correl_id: str
    streamer_socket_url: str
    accounts: list[dict[str, Any]]
    mkt_data_permission: str


class BrokerCredentialRepository:
    def __init__(self, session: Session, encryption_key: bytes) -> None:
        self._session = session
        self._key = encryption_key

    def _by_user_broker(self, user_id: int, broker: str) -> BrokerCredential | None:
        stmt = select(BrokerCredential).where(
            BrokerCredential.user_id == user_id,
            BrokerCredential.broker == broker,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def store_refresh_token(
        self,
        *,
        user_id: int,
        broker: str,
        refresh_token: str,
        expires_at: datetime | None = None,
        notes: str | None = None,
    ) -> BrokerCredential:
        bundle = encrypt(refresh_token.encode("utf-8"), self._key)
        existing = self._by_user_broker(user_id, broker)
        if existing is None:
            row = BrokerCredential(
                user_id=user_id,
                broker=broker,
                encrypted_refresh_token=bundle.ciphertext,
                token_nonce=bundle.nonce,
                token_tag=bundle.tag,
                expires_at=expires_at,
                notes=notes,
            )
            self._session.add(row)
            self._session.flush()
            return row
        existing.encrypted_refresh_token = bundle.ciphertext
        existing.token_nonce = bundle.nonce
        existing.token_tag = bundle.tag
        existing.expires_at = expires_at
        if notes is not None:
            existing.notes = notes
        self._session.flush()
        return existing

    def load_refresh_token(self, *, user_id: int, broker: str) -> str | None:
        row = self._by_user_broker(user_id, broker)
        if row is None:
            return None
        bundle = CipherBundle(
            ciphertext=row.encrypted_refresh_token,
            nonce=row.token_nonce,
            tag=row.token_tag,
        )
        return decrypt(bundle, self._key).decode("utf-8")

    # ------------------------------------------------------------------
    # Schwab-specific metadata (migration 0009)
    # ------------------------------------------------------------------

    def store_schwab_metadata(
        self,
        user_id: int,
        *,
        streamer_customer_id: str,
        streamer_correl_id: str,
        streamer_socket_url: str,
        account_hashes: list[dict[str, Any]],
        mkt_data_permission: str,
    ) -> None:
        """Encrypt + upsert the Schwab preferences bundle.

        Requires a pre-existing ``broker_credentials`` row for
        ``(user_id, "schwab")``. OAuth flow stores the refresh token
        first, then calls this to attach preferences — if the row is
        missing, raises ``LookupError`` so the caller surfaces a clear
        error instead of silently creating a refresh-token-less row.
        """
        row = self._by_user_broker(user_id, "schwab")
        if row is None:
            msg = "schwab broker credential row missing; store refresh token first"
            raise LookupError(msg)

        customer_bundle = encrypt(streamer_customer_id.encode("utf-8"), self._key)
        correl_bundle = encrypt(streamer_correl_id.encode("utf-8"), self._key)
        accounts_json = json.dumps(account_hashes, separators=(",", ":")).encode("utf-8")
        accounts_bundle = encrypt(accounts_json, self._key)

        row.encrypted_streamer_customer_id = customer_bundle.ciphertext
        row.streamer_customer_id_nonce = customer_bundle.nonce
        row.streamer_customer_id_tag = customer_bundle.tag

        row.encrypted_streamer_correl_id = correl_bundle.ciphertext
        row.streamer_correl_id_nonce = correl_bundle.nonce
        row.streamer_correl_id_tag = correl_bundle.tag

        row.encrypted_account_hashes = accounts_bundle.ciphertext
        row.account_hashes_nonce = accounts_bundle.nonce
        row.account_hashes_tag = accounts_bundle.tag

        row.streamer_socket_url = streamer_socket_url
        row.mkt_data_permission = mkt_data_permission

        self._session.flush()

    def load_schwab_metadata(self, user_id: int) -> SchwabMetadata | None:
        """Decrypt + return the Schwab preferences bundle.

        Returns ``None`` when no row exists OR when the row exists but
        has never had Schwab metadata stored (i.e. any of the required
        columns is NULL). This keeps the "half-populated" edge case out
        of caller code — metadata is all-or-nothing.
        """
        row = self._by_user_broker(user_id, "schwab")
        if row is None:
            return None
        required: tuple[Any, ...] = (
            row.encrypted_streamer_customer_id,
            row.streamer_customer_id_nonce,
            row.streamer_customer_id_tag,
            row.encrypted_streamer_correl_id,
            row.streamer_correl_id_nonce,
            row.streamer_correl_id_tag,
            row.encrypted_account_hashes,
            row.account_hashes_nonce,
            row.account_hashes_tag,
            row.streamer_socket_url,
            row.mkt_data_permission,
        )
        if any(v is None for v in required):
            return None

        customer = decrypt(
            CipherBundle(
                ciphertext=_require_bytes(row.encrypted_streamer_customer_id),
                nonce=_require_bytes(row.streamer_customer_id_nonce),
                tag=_require_bytes(row.streamer_customer_id_tag),
            ),
            self._key,
        ).decode("utf-8")
        correl = decrypt(
            CipherBundle(
                ciphertext=_require_bytes(row.encrypted_streamer_correl_id),
                nonce=_require_bytes(row.streamer_correl_id_nonce),
                tag=_require_bytes(row.streamer_correl_id_tag),
            ),
            self._key,
        ).decode("utf-8")
        accounts_raw = decrypt(
            CipherBundle(
                ciphertext=_require_bytes(row.encrypted_account_hashes),
                nonce=_require_bytes(row.account_hashes_nonce),
                tag=_require_bytes(row.account_hashes_tag),
            ),
            self._key,
        )
        accounts = json.loads(accounts_raw.decode("utf-8"))
        if not isinstance(accounts, list):
            msg = "decrypted account hashes payload is not a JSON list"
            raise ValueError(msg)

        return SchwabMetadata(
            streamer_customer_id=customer,
            streamer_correl_id=correl,
            streamer_socket_url=_require_str(row.streamer_socket_url),
            accounts=accounts,
            mkt_data_permission=_require_str(row.mkt_data_permission),
        )

    def record_test_result(
        self,
        user_id: int,
        *,
        status: str,
        latency_ms: int | None,
    ) -> None:
        """Record a broker-health probe result on the Schwab row.

        No-op when the row doesn't exist yet — the scheduler may fire
        before the user has ever completed OAuth. Callers log the
        probe outcome themselves; this method only persists it.
        """
        row = self._by_user_broker(user_id, "schwab")
        if row is None:
            return
        row.last_test_at = datetime.now(UTC)
        row.last_test_status = status
        row.last_test_latency_ms = latency_ms
        self._session.flush()

    def touch_last_refreshed(self, user_id: int) -> None:
        """Stamp ``last_refreshed_at`` with ``now(UTC)`` on the Schwab row.

        Called by the OAuth refresh path after a successful token
        exchange. No-op when the row doesn't exist.
        """
        row = self._by_user_broker(user_id, "schwab")
        if row is None:
            return
        row.last_refreshed_at = datetime.now(UTC)
        self._session.flush()

    def delete(self, *, user_id: int, broker: str) -> bool:
        """Remove the credential row for ``(user_id, broker)``.

        Returns ``True`` if a row was deleted, ``False`` if none existed.
        Used by ``POST /broker/schwab/disconnect`` and by the refresh
        path when Schwab returns ``invalid_grant`` — both code paths
        want the row gone without separately checking existence first.
        """
        row = self._by_user_broker(user_id, broker)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


def _require_bytes(value: bytes | None) -> bytes:
    if value is None:
        msg = "expected non-null bytes column on broker_credentials row"
        raise ValueError(msg)
    return value


def _require_str(value: str | None) -> str:
    if value is None:
        msg = "expected non-null string column on broker_credentials row"
        raise ValueError(msg)
    return value

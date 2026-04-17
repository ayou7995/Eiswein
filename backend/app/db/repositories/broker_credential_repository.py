"""BrokerCredential encrypted storage access.

Ciphertext and key never cross this boundary together — callers pass
plaintext or receive plaintext via the `store` / `load` helpers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BrokerCredential
from app.security.encryption import CipherBundle, decrypt, encrypt


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

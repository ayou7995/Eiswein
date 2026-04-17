"""SQLAlchemy ORM models for Phase 0.

Only the tables needed before the data layer exists:
* `User` (A3) — always single-admin in v1, scaffolded for multi-user.
* `AuditLog` (I9) — append-only event log.
* `Ticker` (A1) — master table so DailyPrice later FKs to tickers, not watchlists.
* `BrokerCredential` (A3, I11) — AES-GCM encrypted Schwab refresh tokens.

Forward-declared relationships to Phase 1 tables (Watchlist/Position/...) use
string references, so Phase 1 just needs to register the target models against
`Base.metadata`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    broker_credentials: Mapped[list["BrokerCredential"]] = relationship(
        "BrokerCredential", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, username={self.username!r})"


class AuditLog(Base):
    """Append-only audit trail (I9).

    Convention: NEVER UPDATE or DELETE rows from application code. Daily
    backups capture these as immutable records.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_event_ip_time", "event_type", "ip", "timestamp"),
    )


class Ticker(Base):
    """Master table of tracked symbols (A1).

    DailyPrice (Phase 1) FKs here, not to Watchlist, so removing from a
    watchlist preserves history.
    """

    __tablename__ = "tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class BrokerCredential(Base):
    """Encrypted broker OAuth credential storage.

    The refresh token is AES-256-GCM encrypted at column level. `nonce`
    and `tag` must be stored alongside `ciphertext` — they are not
    secrets by themselves but are required inputs for decryption.
    """

    __tablename__ = "broker_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "broker", name="uq_broker_credentials_user_broker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False)

    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="broker_credentials")

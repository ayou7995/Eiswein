"""SQLAlchemy ORM models.

Phase 0 tables:
* `User` (A3) — always single-admin in v1, scaffolded for multi-user.
* `AuditLog` (I9) — append-only event log.
* `Ticker` (A1) — master table so DailyPrice FKs to tickers, not watchlists.
* `BrokerCredential` (A3, I11) — AES-GCM encrypted Schwab refresh tokens.

Phase 1 tables (data layer):
* `Watchlist` — user-owned symbol selection (UNIQUE per user+symbol).
* `DailyPrice` — auto-adjusted OHLCV price history keyed by symbol+date.
* `MacroIndicator` — FRED series data keyed by series_id+date.

Phase 2 tables (indicator layer):
* `DailySignal` — per-ticker, per-indicator, per-day IndicatorResult.
  UNIQUE(symbol, date, indicator_name) + ``indicator_version`` column
  (A2): formula bumps don't rewrite history.

Phase 3 tables (signal composition layer):
* `TickerSnapshot` — one row per ticker per trading day: composed
  Action + TimingModifier + entry tiers + stop-loss + posture.
* `MarketSnapshot` — global market posture per trading day.
* `MarketPostureStreak` — consecutive-days streak of the current
  posture for dashboard badges (D3).

Phase 5 tables (positions + trade log):
* `Position` — current (or historical) holdings; ``closed_at`` nullable.
  Partial-unique index on (user_id, symbol) WHERE closed_at IS NULL
  enforces ONE open position per (user, symbol).
* `Trade` — append-only ledger of executed buys / sells. Survives
  position deletion (``position_id`` nullable). ``realized_pnl`` is
  computed at sell time from the position's stored ``avg_cost``;
  never client-supplied.

All user-owned tables carry `user_id` FK (A3). Prices use `Decimal`
(Numeric(12,4) for prices; Numeric(18,6) for shares + cost basis to
support fractional lots and to stop FP drift in P&L math).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


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

    broker_credentials: Mapped[list[BrokerCredential]] = relationship(
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

    __table_args__ = (Index("ix_audit_log_event_ip_time", "event_type", "ip", "timestamp"),)


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

    user: Mapped[User] = relationship("User", back_populates="broker_credentials")


class Watchlist(Base):
    """User-selected symbols for tracking (A1, A3, I4).

    `data_status` is a lightweight state machine used by the cold-start
    backfill path: ``pending`` → ``ready`` (success) or ``failed`` / ``delisted``.
    The frontend polls ``GET /api/v1/ticker/{symbol}?only_status=1`` to
    display the appropriate UI while backfill finishes.
    """

    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
        Index("ix_watchlist_user_symbol", "user_id", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    data_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailyPrice(Base):
    """Auto-adjusted OHLCV keyed by symbol+date (A1, A2).

    Prices are ``Decimal`` (Numeric(12,4)) rather than float so P&L
    calculations aren't subject to binary-float drift. ``close`` is the
    yfinance auto-adjusted close (splits + dividends), which means
    Position.avg_cost (user-input) and DailyPrice.close live in the same
    adjusted-space — see STAFF_REVIEW_DECISIONS.md I1 for the caveat.
    """

    __tablename__ = "daily_price"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_daily_price_symbol_date"),
        Index("ix_daily_price_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)


class MacroIndicator(Base):
    """FRED macro series keyed by series_id+date (A1, A2).

    Example series: ``DGS10``, ``DGS2``, ``DTWEXBGS``, ``FEDFUNDS``,
    ``VIXCLS``. ``series_id`` is the upstream FRED identifier — storing
    it rather than a human name keeps the integration simple when we add
    series later.
    """

    __tablename__ = "macro_indicator"
    __table_args__ = (
        UniqueConstraint("series_id", "date", name="uq_macro_series_date"),
        Index("ix_macro_indicator_series_date", "series_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)


class DailySignal(Base):
    """Per-ticker, per-indicator, per-day computed result (Phase 2, A2).

    One row per ``(symbol, date, indicator_name)``. ``signal`` is the
    ``SignalTone`` string (green/yellow/red/neutral). ``value`` is the
    headline number (nullable when ``data_sufficient=False``).
    ``detail`` holds the raw numeric breakdown for the expand-on-tap
    UI — stored as JSON so schema changes in the indicator modules do
    not require Alembic migrations.

    ``indicator_version`` is persisted per-row (A2): when a formula
    bumps, old rows keep their original version label so historical
    comparison stays meaningful.
    """

    __tablename__ = "daily_signal"
    __table_args__ = (
        UniqueConstraint("symbol", "date", "indicator_name", name="uq_daily_signal_sym_date_ind"),
        Index("ix_daily_signal_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    indicator_name: Mapped[str] = mapped_column(String(40), nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    data_sufficient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    short_label: Mapped[str] = mapped_column(String(120), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    indicator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class TickerSnapshot(Base):
    """Composed per-ticker signal snapshot for one trading day (Phase 3).

    One row per ``(symbol, date)``. Combines the D1a action, D1b timing
    modifier, 3-tier entry suggestion, and dynamic stop-loss. Mirrors
    the :class:`app.signals.types.ComposedSignal` domain type.

    ``market_posture_at_compute`` is snapshotted per-row so that the
    posture surfaced next to the action in the UI is the one that was
    current when the signal was composed (D2 says posture is a context
    badge, never a silent action downgrade).
    """

    __tablename__ = "ticker_snapshot"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_ticker_snapshot_symbol_date"),
        Index("ix_ticker_snapshot_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    direction_green_count: Mapped[int] = mapped_column(Integer, nullable=False)
    direction_red_count: Mapped[int] = mapped_column(Integer, nullable=False)
    timing_modifier: Mapped[str] = mapped_column(String(20), nullable=False)
    show_timing_modifier: Mapped[bool] = mapped_column(Boolean, nullable=False)
    entry_aggressive: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_ideal: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_conservative: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    market_posture_at_compute: Mapped[str] = mapped_column(String(20), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MarketSnapshot(Base):
    """Global market posture snapshot for one trading day (Phase 3, D2).

    One row per trading day. ``regime_{green,red,yellow}_count`` are
    denormalized for dashboard rendering so the frontend doesn't need
    to re-query + re-count the regime indicators.
    """

    __tablename__ = "market_snapshot"
    __table_args__ = (Index("ix_market_snapshot_date", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    posture: Mapped[str] = mapped_column(String(20), nullable=False)
    regime_green_count: Mapped[int] = mapped_column(Integer, nullable=False)
    regime_red_count: Mapped[int] = mapped_column(Integer, nullable=False)
    regime_yellow_count: Mapped[int] = mapped_column(Integer, nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MarketPostureStreak(Base):
    """Consecutive-day streak of the current market posture (D3).

    One row per day. When posture on day N == posture on day N-1,
    ``streak_days`` is N-1's streak + 1 and ``streak_started_on`` is
    preserved. When posture flips, ``streak_days`` resets to 1 and
    ``streak_started_on`` becomes today.

    Streaks ONLY track market posture — per-indicator streaks are
    explicitly excluded (D3: "too much noise").
    """

    __tablename__ = "market_posture_streak"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    current_posture: Mapped[str] = mapped_column(String(20), nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False)
    streak_started_on: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Position(Base):
    """User holding for a single symbol (Phase 5).

    Open-position invariant: at most ONE row per ``(user_id, symbol)``
    with ``closed_at IS NULL``. Enforced by a partial unique index
    created in the Alembic migration (SQLAlchemy's ORM layer cannot
    declare partial uniques portably so it lives as raw DDL there —
    see ``alembic/versions/0005_*.py``). Closed positions preserve the
    row so the ledger + history can still reference them.

    ``shares`` + ``avg_cost`` use Numeric(18,6) for fractional-lot
    precision. ``avg_cost`` is a running weighted average updated on
    buy-side trades; on sell-side trades it is left unchanged and
    realized P&L is recorded on the :class:`Trade` row.

    Prices stored here live in the same auto-adjusted space as
    :class:`DailyPrice.close` — users enter their actual execution
    price, which equals the auto-adjusted value on the execution date
    unless a later split / dividend has adjusted the historical close.
    See STAFF_REVIEW_DECISIONS.md I1 for the caveat.
    """

    __tablename__ = "positions"
    __table_args__ = (
        # NOTE: the open-position partial unique index is defined in the
        # Alembic migration (SQLite/SQLAlchemy portability). A plain
        # UniqueConstraint here would block re-opening a symbol after
        # it's been closed, which we explicitly allow.
        Index("ix_positions_user_symbol", "user_id", "symbol"),
        Index("ix_positions_user_closed", "user_id", "closed_at"),
        CheckConstraint("shares >= 0", name="ck_positions_shares_nonneg"),
        CheckConstraint("avg_cost >= 0", name="ck_positions_avg_cost_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class Trade(Base):
    """Immutable ledger entry for a single executed buy or sell (Phase 5).

    Append-only by convention — no ``updated_at``, no update
    repository method. Once written, a Trade row is a historical
    record.

    ``position_id`` is nullable so the trade log survives position
    deletion / migration — the ``symbol`` column carries the link for
    reporting. ``realized_pnl`` is set by the server on sell trades
    from the position's stored ``avg_cost`` at the moment of sale; it
    is NEVER client-supplied.
    """

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_user_executed_at", "user_id", "executed_at"),
        Index("ix_trades_user_symbol_executed_at", "user_id", "symbol", "executed_at"),
        CheckConstraint("shares > 0", name="ck_trades_shares_positive"),
        CheckConstraint("price > 0", name="ck_trades_price_positive"),
        CheckConstraint("side IN ('buy','sell')", name="ck_trades_side_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

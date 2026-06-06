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

All user-owned tables carry `user_id` FK (A3). Prices use `Decimal`
(Numeric(12,4) for prices).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import date as date_type
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
    text,
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

    # Schwab-specific metadata (nullable — other brokers, or Schwab rows
    # that haven't completed the post-OAuth "user preferences" fetch
    # yet, leave these NULL). Each encrypted blob carries its own
    # nonce/tag pair — AES-GCM requires a fresh nonce per ciphertext.
    encrypted_streamer_customer_id: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    streamer_customer_id_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    streamer_customer_id_tag: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    encrypted_streamer_correl_id: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    streamer_correl_id_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    streamer_correl_id_tag: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # JSON list [{plaintext_acct, hash_value, display_id}] encrypted as
    # a single blob. The plaintext account number is PII; hash_value is
    # what Schwab API calls expect; display_id is a short masked form
    # for the UI.
    encrypted_account_hashes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    account_hashes_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    account_hashes_tag: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Streamer WebSocket URL (e.g. "wss://streamer-api.schwab.com/ws").
    # Not a secret — Schwab publishes the endpoint; storing plain makes
    # debugging easier.
    streamer_socket_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Schwab market-data permission: "NP" (non-pro), "PRO", etc.
    mkt_data_permission: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Last "can we hit the Schwab API?" health check recorded by the
    # token-refresh / broker-test code paths.
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    Hard-delete: DELETE requests remove the row. ``added_at`` remains as
    the sole audit timestamp ("when did I add this?"). Historical-replay
    backfill uses :meth:`WatchlistRepository.distinct_symbols_across_users`
    (current-watchlist semantics) rather than reconstructing per-day
    membership, so the soft-delete tombstone carried no real value.
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

    # Phase B (commit B): folder-style grouping. Nullable — ON DELETE SET
    # NULL when the group disappears so the row survives. The
    # ``selectin`` eager-load avoids the N+1 read pattern on the list
    # endpoint (group_name is denormalized into the response).
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlist_group.id", ondelete="SET NULL"), nullable=True
    )
    group: Mapped[WatchlistGroup | None] = relationship(
        "WatchlistGroup", back_populates="watchlists", lazy="selectin"
    )
    tags: Mapped[list[WatchlistTag]] = relationship(
        "WatchlistTag",
        secondary="watchlist_symbol_tag",
        back_populates="watchlists",
        lazy="selectin",
    )


class WatchlistGroup(Base):
    """Folder-style grouping of watchlist rows (Phase B).

    One row per ``(user_id, name)`` — case-insensitive via the functional
    LOWER(name) unique index in migration 0017. ``position`` keeps the
    sidebar order stable across renames and reorders.

    Group deletion sets ``watchlist.group_id = NULL`` for its members
    (ON DELETE SET NULL) — the watchlist rows survive in the
    "unassigned" bucket and the UI surfaces them under a synthetic
    "未分類" header.
    """

    __tablename__ = "watchlist_group"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_watchlist_group_user_name"),
        Index("ix_watchlist_group_user", "user_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    watchlists: Mapped[list[Watchlist]] = relationship("Watchlist", back_populates="group")


class WatchlistTag(Base):
    """Free-form multi-tag label for watchlist rows (Phase B).

    Color is locked to a 6-digit hex (``#RRGGBB``) at the DB level via a
    CHECK constraint. The repository validates the format too — both
    layers stay in sync so an SQLAlchemy bypass (raw INSERT in a
    migration, say) still fails before the row lands.

    Case-insensitive uniqueness via the functional LOWER(name) index in
    migration 0017 — mirrors the watchlist_group story.
    """

    __tablename__ = "watchlist_tag"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_watchlist_tag_user_name"),
        CheckConstraint(
            "color GLOB '#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]" "[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'",
            name="ck_watchlist_tag_color_hex",
        ),
        Index("ix_watchlist_tag_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    watchlists: Mapped[list[Watchlist]] = relationship(
        "Watchlist",
        secondary="watchlist_symbol_tag",
        back_populates="tags",
    )


class WatchlistSymbolTag(Base):
    """Join table between :class:`Watchlist` and :class:`WatchlistTag`.

    Composite primary key on (watchlist_id, tag_id) gives natural
    idempotency for attach — re-attaching the same tag raises
    IntegrityError which the repository swallows. CASCADE on both FKs
    keeps the table self-cleaning when either side disappears.
    """

    __tablename__ = "watchlist_symbol_tag"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_tag.id", ondelete="CASCADE"), primary_key=True
    )


class DailyPrice(Base):
    """Auto-adjusted OHLCV keyed by symbol+date (A1, A2).

    Prices are ``Decimal`` (Numeric(12,4)) rather than float so
    calculations aren't subject to binary-float drift. ``close`` is the
    yfinance auto-adjusted close (splits + dividends).
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
    # Bumped on every UPSERT so the freshness layer can tell a partial
    # intra-day bar (written before market_close + buffer) apart from a
    # finalized close. The repository sets this explicitly on the ON
    # CONFLICT DO UPDATE clause — raw INSERTs bypass SQLAlchemy's
    # ``onupdate`` hook.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


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
    # v2 (2026-06): actual date of underlying input data the indicator
    # consumed. < ``date`` means the result was carry-forwarded from an
    # older FRED / yfinance / breadth bar — UI surfaces this as a
    # "資料截至 X" pill. Nullable so legacy rows + fallback results
    # without known frame dates can write NULL.
    data_as_of: Mapped[date_type | None] = mapped_column(Date, nullable=True)


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
    # Short-term vote (v2 Phase 1, 2026-06). Mid-term vote above runs on
    # the 4 direction indicators (price_vs_ma / rsi / volume_anomaly /
    # relative_strength); short-term runs on the 4 fastest indicators
    # (rsi / macd / bollinger / volume_anomaly). ``server_default`` lets
    # legacy fixtures + migration 0020 backfill both new + existing rows
    # without having to know about the new columns.
    action_short: Mapped[str] = mapped_column(String(20), nullable=False, server_default="watch")
    direction_short_green_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    direction_short_red_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
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
    # Short-term posture (v2 Phase 1, 2026-06). Mid-term posture above
    # votes on all 4 regime indicators (spx_ma / ad_day / vix /
    # yield_spread); short-term posture votes on the 2 fastest (vix +
    # ad_day) so it can flip on intra-week panic without dragging in
    # the multi-month yield curve signal. ``server_default`` covers
    # legacy fixtures + migration 0020 backfill paths.
    posture_short: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    regime_short_green_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    regime_short_red_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
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


class SystemMetadata(Base):
    """Tiny key-value store for cross-job state (Phase 6).

    Used by the scheduler jobs to record timestamps that don't merit
    their own table:

    * ``last_daily_update_at`` — last time ``run_daily_update`` finished
      (market-open runs only).
    * ``last_backup_at`` — last successful SQLite backup completion.
    * ``last_vacuum_at`` — last successful ``VACUUM`` (used by
      ``jobs/vacuum.py`` to skip runs within 25 days).

    Values are stored as ISO-8601 UTC strings. The repository helpers
    handle the (de)serialization so callers deal in ``datetime``
    objects.
    """

    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class BackfillJob(Base):
    """State row for one long-running job (onboarding or revalidation).

    Two ``kind`` values share this table:

    * ``onboarding`` — a single watchlist symbol's cold-start price
      fetch plus gap-fill of ticker_snapshot rows against every
      existing market_snapshot date. ``symbol`` is non-NULL; ``force``
      is always False (we never overwrite during onboarding).
    * ``revalidation`` — the full historical replay fired when a user
      clicks "re-run indicators". ``symbol`` is NULL; ``force`` is
      True (the whole point is to rewrite stale rows). ``from_date``
      / ``to_date`` span the oldest stored market_snapshot to today.

    Only one row is ever ``pending``/``running`` at a time — the
    repository's :meth:`get_active` helper is the server-side guard
    (repositories don't hold locks, so the scheduler + HTTP layers
    cooperate). Terminal states are ``completed``, ``cancelled``,
    ``failed``; terminal rows set ``finished_at``.

    ``cancel_requested`` is the cooperative-cancel flag flipped by the
    HTTP ``cancel`` endpoint. The orchestrator polls it between days
    and exits cleanly, marking ``state='cancelled'``.

    ``created_by_user_id`` is a plain integer column (no FK) — SQLite
    FK enforcement is off in this codebase and the user table is
    tiny, so adding a constraint here would be ceremony without
    runtime value.
    """

    __tablename__ = "backfill_job"
    __table_args__ = (Index("ix_backfill_job_state_created_at", "state", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ``kind`` discriminates onboarding vs revalidation runs. Migration
    # 0014 gives legacy rows a server default of 'revalidation' so they
    # surface sensibly in the jobs UI.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="revalidation", server_default="revalidation"
    )
    # Non-NULL for onboarding jobs. NULL for revalidation jobs (they
    # span every symbol in the watchlist). Stored upper-cased by the
    # service layer; no FK — the watchlist row can disappear mid-run.
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    processed_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_existing_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class CalendarEvent(Base):
    """Catalyst calendar entry — earnings, macro release, or industry event.

    Single discriminated table keyed by ``type``:

    * ``earnings`` — per-ticker quarterly release; ``ticker_symbol`` set,
      ``payload_json`` may carry ``time_marker`` (BMO/AMC) and
      consensus EPS.
    * ``macro`` — US economic release (CPI, PCE, PPI, NFP, FOMC, PMI);
      ``ticker_symbol`` NULL, ``payload_json`` may carry prior reading.
    * ``industry`` — sector / conference / IPO catalysts (WWDC, GTC);
      ``ticker_symbol`` only when the event ties to a single ticker.

    Dedup is enforced by the functional UNIQUE index in migration 0019
    (``(event_date, type, COALESCE(ticker_symbol, ''), title)``) so the
    daily sync job can re-run idempotently — no transactional upsert
    juggling required at the repository layer.
    """

    __tablename__ = "calendar_event"
    __table_args__ = (
        CheckConstraint(
            "type IN ('earnings', 'macro', 'industry')",
            name="ck_calendar_event_type",
        ),
        Index("ix_calendar_event_date_type", "event_date", "type"),
        Index("ix_calendar_event_ticker", "ticker_symbol", "event_date"),
        # Functional UNIQUE on (event_date, type, COALESCE(ticker_symbol, ''),
        # title) — coalescing NULL to '' so two macro events with the same
        # (date, type, title) collide rather than both inserting (SQLite
        # otherwise treats every NULL as distinct in UNIQUE indexes). The
        # ON CONFLICT clause in :class:`CalendarEventRepository.upsert_many`
        # targets exactly this expression, so the index must live in
        # metadata (not just the migration) for ``Base.metadata.create_all``
        # in tests to create it.
        Index(
            "uq_calendar_event_dedup",
            "event_date",
            "type",
            text("COALESCE(ticker_symbol, '')"),
            "title",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Wall-clock string ("8:30 ET") or BMO/AMC marker. Storing TIME would
    # lose the BMO/AMC distinction which is the most operationally
    # important detail on earnings days.
    event_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    ticker_symbol: Mapped[str | None] = mapped_column(String(10), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

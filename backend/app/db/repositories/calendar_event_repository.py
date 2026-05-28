"""CalendarEvent CRUD — range queries + idempotent upsert.

The sync job re-runs every daily_update; the dedup key on
``(event_date, type, COALESCE(ticker_symbol, ''), title)`` plus the
``on_conflict_do_update`` here mean we can re-insert the same event
many times without ever creating a duplicate row. Payload + time +
source are refreshed on conflict so a downstream data revision (e.g.
yfinance updates a consensus EPS estimate) propagates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, TypedDict

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import CalendarEvent

EventType = str  # 'earnings' | 'macro' | 'industry' — validated by CHECK constraint


class CalendarEventRow(TypedDict, total=False):
    """Row payload for upserts. ``ticker_symbol``, ``event_time``, and
    ``payload_json`` are optional; everything else is mandatory."""

    event_date: date
    event_time: str | None
    type: EventType
    ticker_symbol: str | None
    title: str
    payload_json: dict[str, Any] | None
    source: str


class CalendarEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[CalendarEventRow]) -> int:
        """Upsert events keyed by the functional UNIQUE
        (event_date, type, COALESCE(ticker_symbol, ''), title).

        Re-running the sync hits the conflict branch and updates
        ``event_time``, ``payload_json``, ``source``. The naturally-keyed
        columns (date/type/ticker/title) are left untouched on conflict
        because changing any of those would constitute a different event.
        """
        materialized: list[CalendarEventRow] = list(rows)
        if not materialized:
            return 0
        # Match MacroRepository's defensive batching against
        # SQLITE_MAX_VARIABLE_NUMBER. 7 columns * 500 rows = 3500 binds.
        batch_size = 500
        for start in range(0, len(materialized), batch_size):
            chunk = materialized[start : start + batch_size]
            stmt = sqlite_insert(CalendarEvent).values(chunk)
            # ON CONFLICT target must mirror the functional unique index
            # created in migration 0019 (event_date, type,
            # COALESCE(ticker_symbol, ''), title) exactly — SQLite
            # compares the expression list against indexed expressions
            # textually, so the empty-string default must be emitted as
            # a SQL literal (``''``) rather than a bound parameter
            # (``?``); using ``literal_column`` keeps the SQL string in
            # one piece.
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    CalendarEvent.event_date,
                    CalendarEvent.type,
                    func.coalesce(CalendarEvent.ticker_symbol, literal_column("''")),
                    CalendarEvent.title,
                ],
                set_={
                    "event_time": stmt.excluded.event_time,
                    "payload_json": stmt.excluded.payload_json,
                    "source": stmt.excluded.source,
                },
            )
            self._session.execute(stmt)
        self._session.flush()
        return len(materialized)

    def list_in_range(
        self,
        *,
        start: date,
        end: date,
        types: Sequence[EventType] | None = None,
        ticker_symbols: Sequence[str] | None = None,
    ) -> list[CalendarEvent]:
        """All events with ``start <= event_date <= end``.

        ``types`` filters to one or more event types. ``ticker_symbols``,
        when provided, returns events that EITHER reference one of those
        tickers (earnings, ticker-tied industry) OR are not ticker-scoped
        (macro releases) — i.e. macro events are always included so the
        operator's tag filter doesn't accidentally hide CPI when they
        wanted "just my EV tickers".
        """
        stmt = select(CalendarEvent).where(
            CalendarEvent.event_date >= start,
            CalendarEvent.event_date <= end,
        )
        if types:
            stmt = stmt.where(CalendarEvent.type.in_(types))
        if ticker_symbols:
            normalized = [s.upper() for s in ticker_symbols]
            stmt = stmt.where(
                or_(
                    CalendarEvent.ticker_symbol.in_(normalized),
                    CalendarEvent.ticker_symbol.is_(None),
                )
            )
        stmt = stmt.order_by(
            CalendarEvent.event_date.asc(),
            CalendarEvent.event_time.asc().nullsfirst(),
            CalendarEvent.type.asc(),
            CalendarEvent.id.asc(),
        )
        return list(self._session.execute(stmt).scalars().all())

    def next_for_ticker(
        self,
        *,
        ticker_symbol: str,
        as_of: date,
        types: Sequence[EventType] | None = None,
    ) -> CalendarEvent | None:
        """Earliest upcoming event for a ticker on or after ``as_of``.

        Used by the TickerDetail "next catalyst" chip and the
        Earnings Date Proximity indicator. ``as_of`` is usually today
        but kept as a parameter for backfill / time-travel testing.
        """
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.ticker_symbol == ticker_symbol.upper(),
                CalendarEvent.event_date >= as_of,
            )
            .order_by(CalendarEvent.event_date.asc(), CalendarEvent.id.asc())
            .limit(1)
        )
        if types:
            stmt = stmt.where(CalendarEvent.type.in_(types))
        return self._session.execute(stmt).scalar_one_or_none()

    def upcoming_macro(
        self,
        *,
        as_of: date,
        days: int,
    ) -> list[CalendarEvent]:
        """Macro events occurring on [as_of, as_of+days).

        Used by the MarketOverview "this week's data" banner and the
        catalyst digest email assembler.
        """
        end = date.fromordinal(as_of.toordinal() + max(0, days))
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.type == "macro",
                CalendarEvent.event_date >= as_of,
                CalendarEvent.event_date < end,
            )
            .order_by(CalendarEvent.event_date.asc(), CalendarEvent.id.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def delete_orphans_for_symbols(self, removed_symbols: Iterable[str]) -> int:
        """Drop earnings + ticker-tied industry events for symbols that
        left the watchlist. Macro events untouched.

        Called by ``calendar_sync`` after computing the active watchlist
        — we keep the table compact and avoid stale chips appearing on
        symbols re-added later (a fresh sync re-fetches anyway).
        """
        normalized = [s.upper() for s in removed_symbols if s and s.strip()]
        if not normalized:
            return 0
        stmt = select(CalendarEvent.id).where(
            and_(
                CalendarEvent.ticker_symbol.in_(normalized),
                CalendarEvent.type.in_(("earnings", "industry")),
            )
        )
        ids = list(self._session.execute(stmt).scalars().all())
        if not ids:
            return 0
        # ORM bulk delete via PK is fine for v1 scale (<200 rows per
        # purge). For larger scales swap to a single DELETE...WHERE.
        for event_id in ids:
            event = self._session.get(CalendarEvent, event_id)
            if event is not None:
                self._session.delete(event)
        self._session.flush()
        return len(ids)

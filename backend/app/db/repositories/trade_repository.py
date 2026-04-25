"""Trade log — append-only ledger (Phase 5).

Same convention as :class:`AuditRepository`: NO update or delete
methods. Every trade is an immutable historical event. Positions may
be deleted / migrated over time; trades persist (``position_id`` is
``ON DELETE SET NULL``).

Realized P&L is NEVER client-supplied. The route layer computes it
from the position's stored ``avg_cost`` via :meth:`PositionRepository.apply_sell`
and passes the result in — the API schema has no field for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Trade

TradeSide = Literal["buy", "sell"]


class TradeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        user_id: int,
        position_id: int | None,
        symbol: str,
        side: TradeSide,
        shares: Decimal,
        price: Decimal,
        executed_at: datetime,
        realized_pnl: Decimal | None = None,
        note: str | None = None,
        source: str = "manual",
        external_id: str | None = None,
    ) -> Trade:
        row = Trade(
            user_id=user_id,
            position_id=position_id,
            symbol=symbol.upper(),
            side=side,
            shares=shares,
            price=price,
            executed_at=executed_at,
            realized_pnl=realized_pnl,
            note=note,
            source=source,
            external_id=external_id,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def find_by_external_id(self, *, user_id: int, source: str, external_id: str) -> Trade | None:
        """Lookup a trade by its broker-supplied identifier.

        Used by broker-CSV importers to skip rows that have already been
        ingested. The uniqueness is enforced at the DB level by the
        partial unique index ``uq_trades_source_external_id`` — this
        method is a convenience read-only helper, not a correctness
        guard.
        """
        stmt = select(Trade).where(
            Trade.user_id == user_id,
            Trade.source == source,
            Trade.external_id == external_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_for_user(
        self,
        *,
        user_id: int,
        symbol: str | None = None,
        side: TradeSide | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> Sequence[Trade]:
        filters = [Trade.user_id == user_id]
        if symbol is not None:
            filters.append(Trade.symbol == symbol.upper())
        if side is not None:
            filters.append(Trade.side == side)
        if start_date is not None:
            # Trade.executed_at is a datetime — cast the date via the
            # start-of-day comparison; SQLAlchemy's Date vs DateTime
            # comparison is well-defined in SQLite.
            filters.append(Trade.executed_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date is not None:
            filters.append(Trade.executed_at <= datetime.combine(end_date, datetime.max.time()))
        stmt = select(Trade).where(*filters).order_by(Trade.executed_at.desc(), Trade.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return self._session.execute(stmt).scalars().all()

    def list_for_position(
        self,
        *,
        user_id: int,
        position_id: int,
        limit: int | None = None,
    ) -> Sequence[Trade]:
        """Trades for a specific position, scoped to the owning user.

        The ``user_id`` filter is applied in addition to the position FK
        — an attacker with a guessed position_id cannot leak another
        user's trades even if the FK were somehow reassigned.
        """
        stmt = (
            select(Trade)
            .where(
                Trade.user_id == user_id,
                Trade.position_id == position_id,
            )
            .order_by(Trade.executed_at.desc(), Trade.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return self._session.execute(stmt).scalars().all()

    def count_for_user(self, user_id: int) -> int:
        from sqlalchemy import func

        stmt = select(func.count(Trade.id)).where(Trade.user_id == user_id)
        return int(self._session.execute(stmt).scalar_one())

    def count_all(self) -> int:
        from sqlalchemy import func

        return int(self._session.execute(select(func.count(Trade.id))).scalar_one())

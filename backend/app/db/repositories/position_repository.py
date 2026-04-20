"""Position CRUD — user-scoped (Phase 5).

All reads + writes are user-scoped. Callers MUST pass ``user_id``
explicitly so a bug in the route layer can never leak a cross-user
position (security-critical).

Business rules enforced here (belt-and-suspenders — the API layer
also validates; defense-in-depth):
* Only one OPEN position per (user, symbol). The DB partial-unique
  index (migration 0005) is the final backstop; :meth:`create_open`
  also checks explicitly so we can surface :class:`ConflictError`
  with a useful message rather than an opaque IntegrityError.
* Shares and avg_cost use :class:`Decimal` arithmetic throughout —
  NEVER ``float`` — so 10 years of fractional-lot math doesn't drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Position
from app.security.exceptions import ConflictError, EisweinError, NotFoundError


class OpenPositionExistsError(ConflictError):
    code = "position_open_exists"
    message = "已有未結清部位，請先操作現有部位"


class PositionClosedError(ConflictError):
    code = "position_closed"
    message = "部位已結清，無法再操作"


class PositionHasRemainingSharesError(ConflictError):
    code = "has_remaining_shares"
    message = "部位仍有持股，請先出清"


class InsufficientSharesError(ConflictError):
    code = "insufficient_shares"
    message = "減倉股數超過持股"


class PositionNotFoundError(NotFoundError):
    code = "position_not_found"
    message = "找不到部位"


class InvalidPositionStateError(EisweinError):
    """Defensive guard for programming bugs (e.g. adding to a closed
    position without going through the API layer's ``409``). Surfaces as
    500 because it indicates the caller should have prevented this.
    """

    http_status = 500
    code = "position_invalid_state"
    message = "部位狀態錯誤"


class PositionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Reads ------------------------------------------------------------

    def get_by_id(self, *, user_id: int, position_id: int) -> Position | None:
        """User-scoped fetch — returns None if not owned by ``user_id``.

        The ``user_id`` filter is critical: cross-user reads must never
        be possible even if the route layer forgets to check.
        """
        stmt = select(Position).where(
            Position.id == position_id,
            Position.user_id == user_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_open_for_symbol(self, *, user_id: int, symbol: str) -> Position | None:
        stmt = select(Position).where(
            Position.user_id == user_id,
            Position.symbol == symbol.upper(),
            Position.closed_at.is_(None),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_open_for_user(self, user_id: int) -> Sequence[Position]:
        stmt = (
            select(Position)
            .where(Position.user_id == user_id, Position.closed_at.is_(None))
            .order_by(Position.opened_at.asc(), Position.id.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def list_all_for_user(self, user_id: int) -> Sequence[Position]:
        stmt = (
            select(Position)
            .where(Position.user_id == user_id)
            .order_by(Position.opened_at.desc(), Position.id.desc())
        )
        return self._session.execute(stmt).scalars().all()

    def count_for_user(self, user_id: int, *, include_closed: bool = False) -> int:
        stmt = select(func.count(Position.id)).where(Position.user_id == user_id)
        if not include_closed:
            stmt = stmt.where(Position.closed_at.is_(None))
        return int(self._session.execute(stmt).scalar_one())

    def count_all(self) -> int:
        return int(self._session.execute(select(func.count(Position.id))).scalar_one())

    # --- Writes -----------------------------------------------------------

    def create_open(
        self,
        *,
        user_id: int,
        symbol: str,
        shares: Decimal,
        avg_cost: Decimal,
        opened_at: datetime,
        notes: str | None = None,
    ) -> Position:
        if shares <= 0:
            msg = "shares must be positive"
            raise InvalidPositionStateError(msg)
        if avg_cost <= 0:
            msg = "avg_cost must be positive"
            raise InvalidPositionStateError(msg)
        normalized = symbol.upper()
        if self.get_open_for_symbol(user_id=user_id, symbol=normalized) is not None:
            raise OpenPositionExistsError(details={"symbol": normalized})
        row = Position(
            user_id=user_id,
            symbol=normalized,
            shares=shares,
            avg_cost=avg_cost,
            opened_at=opened_at,
            closed_at=None,
            notes=notes,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def apply_buy(
        self,
        position: Position,
        *,
        shares: Decimal,
        price: Decimal,
    ) -> None:
        """Apply a buy-side trade: weighted-average the cost basis.

        Formula (exact, no float):
            new_shares  = old_shares + buy_shares
            new_avgcost = (old_shares * old_avgcost + buy_shares * buy_price)
                          / new_shares

        Mutates the passed row in place and flushes. The caller owns
        creating the :class:`Trade` row in the same transaction.
        """
        if position.closed_at is not None:
            raise PositionClosedError(details={"position_id": position.id})
        if shares <= 0:
            msg = "buy shares must be positive"
            raise InvalidPositionStateError(msg)
        if price <= 0:
            msg = "buy price must be positive"
            raise InvalidPositionStateError(msg)
        old_shares: Decimal = position.shares
        old_cost: Decimal = position.avg_cost
        new_shares = old_shares + shares
        # Guard against a zero denominator when the position row has
        # somehow drifted to 0 shares without being closed — should not
        # happen through the API but the division would otherwise
        # explode. Treat the buy as a re-open at the new price.
        if new_shares == 0:  # pragma: no cover — defensive
            msg = "position shares totalled zero during buy"
            raise InvalidPositionStateError(msg)
        weighted_cost = (old_shares * old_cost + shares * price) / new_shares
        position.shares = new_shares
        position.avg_cost = weighted_cost
        self._session.flush()

    def apply_sell(
        self,
        position: Position,
        *,
        shares: Decimal,
        price: Decimal,
    ) -> Decimal:
        """Apply a sell-side trade: decrement shares, return realized P&L.

        Returns the realized P&L amount for the caller to persist on
        the corresponding :class:`Trade`. Auto-closes the position if
        the resulting share count is zero.

        Formula: realized_pnl = (price - avg_cost) * shares
        avg_cost is preserved on partial sells.
        """
        if position.closed_at is not None:
            raise PositionClosedError(details={"position_id": position.id})
        if shares <= 0:
            msg = "sell shares must be positive"
            raise InvalidPositionStateError(msg)
        if price <= 0:
            msg = "sell price must be positive"
            raise InvalidPositionStateError(msg)
        if shares > position.shares:
            raise InsufficientSharesError(
                details={
                    "position_id": position.id,
                    "requested": str(shares),
                    "available": str(position.shares),
                }
            )
        realized = (price - position.avg_cost) * shares
        position.shares = position.shares - shares
        if position.shares == 0:
            position.closed_at = datetime.now(UTC)
        self._session.flush()
        return realized

    def close_if_empty(self, position: Position) -> None:
        """Soft-close a position that already has zero shares.

        Called by the DELETE route. Refuses to close a position that
        still holds shares — the caller must zero out via ``reduce``
        first. This guarantees the ledger + position.closed_at stay
        consistent.
        """
        if position.closed_at is not None:
            return
        if position.shares != 0:
            raise PositionHasRemainingSharesError(
                details={"position_id": position.id, "shares": str(position.shares)},
            )
        position.closed_at = datetime.now(UTC)
        self._session.flush()

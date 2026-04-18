"""Watchlist CRUD — user-scoped.

All reads + writes are user-scoped (A3) — callers must pass
``user_id`` explicitly. This keeps the multi-user story honest even
while v1 only has a single admin: no one can accidentally leak
cross-user data by forgetting to filter.

The hard cap (default 100, per B3) is enforced at insert time and
surfaces as a :class:`WatchlistFullError` 422 — yfinance's bulk
download degrades past ~100 symbols and that's why this ceiling
exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Watchlist
from app.security.exceptions import ConflictError, EisweinError, NotFoundError


class WatchlistFullError(EisweinError):
    http_status = 422
    code = "watchlist_full"
    message = "Watchlist 已達上限"


class DuplicateWatchlistEntryError(ConflictError):
    code = "watchlist_duplicate"
    message = "此標的已經在 Watchlist"


class WatchlistRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: int) -> Sequence[Watchlist]:
        stmt = (
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.added_at.asc(), Watchlist.id.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def count_for_user(self, user_id: int) -> int:
        stmt = select(func.count(Watchlist.id)).where(Watchlist.user_id == user_id)
        result = self._session.execute(stmt).scalar_one()
        return int(result)

    def get(self, *, user_id: int, symbol: str) -> Watchlist | None:
        stmt = select(Watchlist).where(
            Watchlist.user_id == user_id,
            Watchlist.symbol == symbol.upper(),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def add(
        self,
        *,
        user_id: int,
        symbol: str,
        max_size: int,
    ) -> Watchlist:
        normalized = symbol.upper()
        if self.get(user_id=user_id, symbol=normalized) is not None:
            raise DuplicateWatchlistEntryError(details={"symbol": normalized})
        if self.count_for_user(user_id) >= max_size:
            raise WatchlistFullError(details={"max_size": max_size})
        row = Watchlist(user_id=user_id, symbol=normalized, data_status="pending")
        self._session.add(row)
        self._session.flush()
        return row

    def remove(self, *, user_id: int, symbol: str) -> None:
        row = self.get(user_id=user_id, symbol=symbol)
        if row is None:
            raise NotFoundError(details={"symbol": symbol.upper()})
        self._session.delete(row)
        self._session.flush()

    def set_status(
        self,
        *,
        user_id: int,
        symbol: str,
        status: str,
        mark_refreshed: bool = False,
    ) -> Watchlist:
        row = self.get(user_id=user_id, symbol=symbol)
        if row is None:
            raise NotFoundError(details={"symbol": symbol.upper()})
        row.data_status = status
        if mark_refreshed:
            row.last_refresh_at = datetime.now(UTC)
        self._session.flush()
        return row

    def distinct_symbols_across_users(self) -> Sequence[str]:
        """All symbols in any user's watchlist — used by ``run_daily_update``.

        Returns uppercased symbols sorted deterministically so the bulk
        download request is reproducible (helps cache hit rates).
        """
        stmt = select(Watchlist.symbol).distinct().order_by(Watchlist.symbol.asc())
        rows = self._session.execute(stmt).scalars().all()
        return [s.upper() for s in rows]

    def list_all_for_symbol(self, symbol: str) -> Sequence[Watchlist]:
        """Every user's row for ``symbol``. Used by daily_update to
        broadcast the new ``data_status`` after a shared bulk fetch.
        """
        stmt = select(Watchlist).where(Watchlist.symbol == symbol.upper())
        return self._session.execute(stmt).scalars().all()

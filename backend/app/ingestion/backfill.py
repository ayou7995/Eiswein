"""Cold-start single-ticker backfill (I4).

Invoked by ``POST /api/v1/watchlist`` when the user adds a new ticker.
The route wraps this in ``asyncio.timeout(5)`` — if we finish in time
the response is ``200 { data_status: "ready" }``; if not, the route
hands off to a ``BackgroundTask`` and returns ``202 { data_status:
"pending" }``.

Invariants:
* Per-symbol :class:`asyncio.Lock` prevents parallel fetches (I4).
* ``watchlist.data_status`` is the state machine: ``pending`` →
  ``ready`` / ``failed`` / ``delisted``. We never re-fetch when it's
  already ``ready`` unless ``force=True``.
* On empty-frame response (yfinance can't find the symbol) we set
  ``delisted`` and surface :class:`DataSourceError` (I18).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.datasources.base import DataSource
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.locks import get_symbol_lock
from app.ingestion.persist import iter_daily_price_rows
from app.security.exceptions import DataSourceError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger("eiswein.ingestion.backfill")

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DELISTED = "delisted"


async def backfill_ticker(
    symbol: str,
    *,
    user_id: int,
    db: "Session",
    data_source: DataSource,
    years: int = 2,
    force: bool = False,
) -> str:
    """Fetch + persist 2y of OHLCV for ``symbol``; return final data_status.

    ``db`` is an already-open session the caller is responsible for
    committing (routes delegate via FastAPI's ``get_db_session``
    dependency; background tasks must commit before returning).
    """
    normalized = symbol.upper()
    lock = await get_symbol_lock(normalized)

    # The route already validated ownership via Pydantic + repository
    # lookup, but background-task re-runs might land after the user has
    # deleted the row. Gracefully no-op rather than creating orphans.
    async with lock:
        watchlist = WatchlistRepository(db)
        prices = DailyPriceRepository(db)

        row = watchlist.get(user_id=user_id, symbol=normalized)
        if row is None:
            raise NotFoundError(details={"symbol": normalized})

        if not force and row.data_status == STATUS_READY:
            return row.data_status

        period = f"{years}y"
        try:
            bulk = await data_source.bulk_download([normalized], period=period)
        except DataSourceError as exc:
            _mark(watchlist, user_id=user_id, symbol=normalized, status=STATUS_FAILED)
            db.commit()
            logger.warning(
                "backfill_data_source_error",
                symbol=normalized,
                details=exc.details,
            )
            raise

        frame = bulk.get(normalized)
        if frame is None or frame.empty:
            _mark(
                watchlist,
                user_id=user_id,
                symbol=normalized,
                status=STATUS_DELISTED,
            )
            db.commit()
            raise DataSourceError(
                details={"reason": "delisted_or_invalid", "symbol": normalized}
            )

        inserted = prices.upsert_many(iter_daily_price_rows(normalized, frame))
        _mark(
            watchlist,
            user_id=user_id,
            symbol=normalized,
            status=STATUS_READY,
            mark_refreshed=True,
        )
        db.commit()
        logger.info(
            "backfill_complete",
            symbol=normalized,
            rows=inserted,
            user_id=user_id,
        )
        return STATUS_READY


def _mark(
    watchlist: WatchlistRepository,
    *,
    user_id: int,
    symbol: str,
    status: str,
    mark_refreshed: bool = False,
) -> None:
    watchlist.set_status(
        user_id=user_id,
        symbol=symbol,
        status=status,
        mark_refreshed=mark_refreshed,
    )

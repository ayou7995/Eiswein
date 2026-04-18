"""Watchlist CRUD + cold-start backfill.

Key behaviors:
* ``POST`` normalizes + validates the symbol (I17), inserts the row,
  then tries to backfill within a 5-second budget. On success →
  ``200 { data_status: "ready" }``. On timeout → ``202 { data_status:
  "pending" }`` and a background task finishes the work. The frontend
  polls ``GET /api/v1/ticker/{symbol}?only_status=1`` until ``ready``.
* Hard cap (B3, default 100) enforced in the repository — HTTP 422.
* Duplicate symbol for same user → ``409`` via :class:`ConflictError`.
* Delisted / invalid tickers surface with ``data_status=delisted``
  (I18) — the DELETE still succeeds so the user can clear them.

This module intentionally does NOT use ``from __future__ import
annotations`` — slowapi's decorator wrapper confuses FastAPI's
forward-ref resolution when body models are referenced as strings
(Phase 0 smoke test regression).
"""

import asyncio
import re
from datetime import datetime
from typing import Literal

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    current_user_id,
    get_data_source_dep,
    get_db_session,
    get_settings_dep,
    get_watchlist_repository,
)
from app.config import Settings
from app.datasources.base import DataSource
from app.db.models import Watchlist
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.backfill import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    backfill_ticker,
)
from app.security.exceptions import DataSourceError, NotFoundError
from app.security.exceptions import ValidationError as EisweinValidationError
from app.security.rate_limit import limiter

router = APIRouter(tags=["watchlist"])
logger = structlog.get_logger("eiswein.watchlist")

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
_COLD_START_BUDGET_SECONDS = 5.0


class SymbolInput(BaseModel):
    """Validated ticker input per I17."""

    symbol: str = Field(min_length=1, max_length=10)

    @field_validator("symbol", mode="before")
    @classmethod
    def _normalize(cls, raw: object) -> str:
        if not isinstance(raw, str):
            msg = "symbol must be a string"
            raise ValueError(msg)
        cleaned = raw.strip().upper()
        if not _SYMBOL_RE.match(cleaned):
            msg = "symbol must match ^[A-Z0-9.\\-]{1,10}$"
            raise ValueError(msg)
        return cleaned


DataStatusLiteral = Literal["pending", "ready", "failed", "delisted"]


class WatchlistItem(BaseModel):
    symbol: str
    data_status: DataStatusLiteral
    added_at: datetime
    last_refresh_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Watchlist) -> "WatchlistItem":
        return cls(
            symbol=row.symbol,
            data_status=_coerce_status(row.data_status),
            added_at=row.added_at,
            last_refresh_at=row.last_refresh_at,
        )


class WatchlistListResponse(BaseModel):
    data: list[WatchlistItem]
    total: int
    has_more: bool = False


class WatchlistCreateResponse(BaseModel):
    data: WatchlistItem


class OkResponse(BaseModel):
    ok: bool = True


def _coerce_status(raw: str) -> DataStatusLiteral:
    # Guard against future rows being added with a status we haven't
    # enumerated here. Treat anything unexpected as "failed" so the UI
    # at least renders.
    if raw in ("pending", "ready", "failed", "delisted"):
        return raw  # type: ignore[return-value]
    return "failed"


def validate_symbol_or_raise(symbol: str) -> str:
    """Normalize + validate a symbol, raising :class:`EisweinValidationError`
    (422) so the global handler emits the standard envelope rather than
    FastAPI's internal 500 on an uncaught pydantic error.
    """
    try:
        return SymbolInput(symbol=symbol).symbol
    except ValidationError as exc:
        from app.security.error_handlers import sanitize_validation_errors

        raise EisweinValidationError(
            details={"errors": sanitize_validation_errors(exc.errors())},
        ) from exc


@router.get(
    "/watchlist",
    response_model=WatchlistListResponse,
    summary="List this user's watchlist (paginated wrapper)",
)
def list_watchlist(
    user_id: int = Depends(current_user_id),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> WatchlistListResponse:
    rows = repo.list_for_user(user_id)
    items = [WatchlistItem.from_row(row) for row in rows]
    return WatchlistListResponse(
        data=items,
        total=len(items),
        has_more=False,
    )


@router.post(
    "/watchlist",
    response_model=WatchlistCreateResponse,
    status_code=status.HTTP_200_OK,
    summary="Add a ticker with immediate backfill (cold-start)",
)
@limiter.limit("10/minute")
async def add_to_watchlist(
    request: Request,
    response: Response,
    payload: SymbolInput,
    background: BackgroundTasks,
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
    session: Session = Depends(get_db_session),
    data_source: DataSource = Depends(get_data_source_dep),
) -> WatchlistCreateResponse:
    row = repo.add(
        user_id=user_id,
        symbol=payload.symbol,
        max_size=settings.watchlist_max_size,
    )
    session.commit()

    try:
        async with asyncio.timeout(_COLD_START_BUDGET_SECONDS):
            final_status = await backfill_ticker(
                payload.symbol,
                user_id=user_id,
                db=session,
                data_source=data_source,
            )
    except TimeoutError:
        # Hand off to a background task. Use a fresh session factory
        # bound to the app so the request's session can close cleanly.
        _schedule_background_backfill(
            request,
            background,
            symbol=payload.symbol,
            user_id=user_id,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return WatchlistCreateResponse(
            data=WatchlistItem(
                symbol=payload.symbol,
                data_status=STATUS_PENDING,  # type: ignore[arg-type]
                added_at=row.added_at,
                last_refresh_at=row.last_refresh_at,
            )
        )
    except DataSourceError as exc:
        logger.warning(
            "cold_start_data_source_error",
            symbol=payload.symbol,
            details=exc.details,
        )
        session.refresh(row)
        return WatchlistCreateResponse(data=WatchlistItem.from_row(row))

    session.refresh(row)
    response.status_code = (
        status.HTTP_200_OK if final_status == STATUS_READY else status.HTTP_202_ACCEPTED
    )
    return WatchlistCreateResponse(data=WatchlistItem.from_row(row))


@router.delete(
    "/watchlist/{symbol}",
    response_model=OkResponse,
    summary="Remove a ticker from this user's watchlist",
)
def remove_from_watchlist(
    symbol: str,
    user_id: int = Depends(current_user_id),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> OkResponse:
    # Re-run SymbolInput validation so invalid strings get a 422 rather
    # than a 404 for an impossible-to-match symbol.
    validated = validate_symbol_or_raise(symbol)
    repo.remove(user_id=user_id, symbol=validated)
    return OkResponse()


def _schedule_background_backfill(
    request: Request,
    background: BackgroundTasks,
    *,
    symbol: str,
    user_id: int,
) -> None:
    factory: sessionmaker[Session] = request.app.state.session_factory
    data_source: DataSource = request.app.state.data_source

    async def _run() -> None:
        # Opens its own session — the request session is already
        # closed by the time this task runs.
        local: Session = factory()
        try:
            await backfill_ticker(
                symbol,
                user_id=user_id,
                db=local,
                data_source=data_source,
            )
        except DataSourceError as exc:
            logger.warning(
                "background_backfill_data_source_error",
                symbol=symbol,
                details=exc.details,
            )
        except NotFoundError:
            # The user may have deleted the watchlist row between the
            # 202 response and the task firing. Nothing to do.
            logger.info("background_backfill_row_removed", symbol=symbol)
        except Exception as exc:
            # Structured log + mark failed so UI can surface it.
            logger.exception("background_backfill_failed", symbol=symbol)
            try:
                repo = WatchlistRepository(local)
                repo.set_status(user_id=user_id, symbol=symbol, status=STATUS_FAILED)
                local.commit()
            except Exception:
                local.rollback()
            raise exc
        finally:
            local.close()

    background.add_task(_run)

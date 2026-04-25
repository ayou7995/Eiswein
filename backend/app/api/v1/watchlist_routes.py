"""Watchlist CRUD + symbol onboarding (Phase 1 UX overhaul).

Key behaviors:
* ``POST /api/v1/watchlist`` does **pessimistic validation**: a
  lightweight pre-flight yfinance call confirms the symbol exists
  (empty frame → 400 invalid_ticker) before any row is written. On
  success we insert the watchlist row with ``data_status='pending'``,
  create an onboarding :class:`BackfillJob`, spawn its runner thread,
  and return 201 with ``job_id`` so the client can poll progress at
  ``GET /api/v1/jobs/{id}``.
* The cold-start "5-second sync budget then BackgroundTask" path is
  gone — onboarding is always asynchronous now. The user gets instant
  feedback (row appears as "pending") and snapshot history back-fills
  in the background.
* ``DELETE /api/v1/watchlist/{symbol}`` — SPY is protected (403
  spy_is_system). If an onboarding job is active, its cancel flag is
  flipped before we hard-delete the watchlist row; the runner exits
  at the next per-day cooperative cancel check.
* Hard cap (B3, default 100) enforced in the repository — HTTP 422.
* Duplicate symbol for same user → ``409`` via
  :class:`DuplicateWatchlistEntryError`.

This module intentionally does NOT use ``from __future__ import
annotations`` — slowapi's decorator wrapper confuses FastAPI's
forward-ref resolution when body models are referenced as strings
(Phase 0 smoke test regression).
"""

import re
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
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
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.backfill import STATUS_PENDING
from app.ingestion.locks import get_user_lock
from app.security.exceptions import (
    DataSourceError,
    EisweinError,
    NotFoundError,
)
from app.security.exceptions import ValidationError as EisweinValidationError
from app.security.rate_limit import limiter
from app.services.symbol_onboarding_service import (
    OnboardingAlreadyRunningError,
    SymbolOnboardingService,
)

router = APIRouter(tags=["watchlist"])
logger = structlog.get_logger("eiswein.watchlist")

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
# SPY is the system benchmark — pinned into daily_update and used by
# multiple regime indicators. The user is never allowed to remove it.
_SYSTEM_SYMBOLS = frozenset({"SPY"})
# How long to wait on the pre-flight yfinance probe. yfinance's
# Ticker.history() for a valid symbol typically returns in <500 ms;
# we give it 3 seconds to absorb brief upstream slowness before we
# surface a 503 "try again later".
_PREFLIGHT_BUDGET_SECONDS = 3.0


class SystemSymbolRemovalError(EisweinError):
    """403 — the system-benchmark symbol (SPY) cannot be removed."""

    http_status = 403
    code = "spy_is_system"
    message = "SPY 為系統基準，無法移除"


class InvalidTickerError(EisweinError):
    """400 — the pre-flight probe returned an empty frame for the symbol.

    Distinct from a validation error (422 for bad format): this one
    fires when the format is legal but yfinance has never heard of the
    ticker (typo, delisted).
    """

    http_status = 400
    code = "invalid_ticker"
    message = "此股票代碼無效"


class PreflightUnavailableError(EisweinError):
    """503 — upstream data source errored during pre-flight.

    Transient vs. invalid is distinguished by raising InvalidTicker on
    empty frames (the provider answered, it just has no data) vs. this
    on :class:`DataSourceError` (the provider never answered).
    """

    http_status = 503
    code = "preflight_unavailable"
    message = "資料來源暫時無法驗證股票代碼，請稍後重試"


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
    # Populated by the list endpoint so the UI can link "in progress"
    # rows to their onboarding job without a second round-trip. None
    # when the symbol is not currently onboarding.
    active_onboarding_job_id: int | None = None
    is_system: bool = False

    @classmethod
    def from_row(
        cls,
        row: Watchlist,
        *,
        active_onboarding_job_id: int | None = None,
    ) -> "WatchlistItem":
        return cls(
            symbol=row.symbol,
            data_status=_coerce_status(row.data_status),
            added_at=row.added_at,
            last_refresh_at=row.last_refresh_at,
            active_onboarding_job_id=active_onboarding_job_id,
            is_system=row.symbol.upper() in _SYSTEM_SYMBOLS,
        )


class WatchlistListResponse(BaseModel):
    data: list[WatchlistItem]
    total: int
    has_more: bool = False


class WatchlistCreateResponse(BaseModel):
    """Response shape for a successful ``POST /watchlist``.

    Always 201 under the new async-only flow. The client polls
    ``GET /api/v1/jobs/{job_id}`` until the job completes.
    """

    data: WatchlistItem
    job_id: int


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
    session: Session = Depends(get_db_session),
) -> WatchlistListResponse:
    rows = repo.list_for_user(user_id)
    job_repo = BackfillJobRepository(session)
    items: list[WatchlistItem] = []
    for row in rows:
        active_id: int | None = None
        if row.data_status == STATUS_PENDING:
            active_job = job_repo.get_active_onboarding(user_id=user_id, symbol=row.symbol)
            if active_job is not None:
                active_id = active_job.id
        items.append(WatchlistItem.from_row(row, active_onboarding_job_id=active_id))
    return WatchlistListResponse(
        data=items,
        total=len(items),
        has_more=False,
    )


@router.post(
    "/watchlist",
    response_model=WatchlistCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a ticker (pessimistic validation, async onboarding)",
)
@limiter.limit("10/minute")
async def add_to_watchlist(
    request: Request,
    response: Response,
    payload: SymbolInput,
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
    session: Session = Depends(get_db_session),
    data_source: DataSource = Depends(get_data_source_dep),
) -> WatchlistCreateResponse:
    # (1) Pre-flight probe. yfinance returns an empty DataFrame for an
    # unknown symbol, a populated one for a valid ticker — this cheap
    # call lets us surface "typo" as 400 without ever creating a DB
    # row. DataSourceError is mapped to 503 so transient upstream
    # failures are distinguishable from permanent invalidity.
    await _preflight_symbol(payload.symbol, data_source=data_source)

    # (2) Serialize per-user add so a double-POST cannot slip past the
    # cap. count→add is two SQL statements, and SQLite has no ATOMIC
    # construct that covers the pair; the user lock is our only guard.
    async with await get_user_lock(user_id):
        row = repo.add(
            user_id=user_id,
            symbol=payload.symbol,
            max_size=settings.watchlist_max_size,
        )
        session.commit()

    # (3) Spawn the onboarding runner. Service uses a fresh session
    # factory internally so the request-scoped session is not shared
    # across threads.
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    run_inline = bool(getattr(request.app.state, "onboarding_run_inline", False))
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=data_source,
        run_inline=run_inline,
    )
    try:
        job = service.start(symbol=payload.symbol, user_id=user_id)
    except OnboardingAlreadyRunningError:
        # Another job is in flight. The watchlist row we just inserted
        # is still valid — the user can retry the onboarding later via
        # re-adding (remove + add) once the queue clears. We return the
        # row itself so the UI doesn't show a phantom "insertion
        # failed" message; the ``active_onboarding_job_id`` field is
        # None so the UI can show a "waiting for job" badge.
        logger.info(
            "watchlist_onboarding_deferred_existing_job",
            symbol=payload.symbol,
        )
        session.refresh(row)
        return WatchlistCreateResponse(
            data=WatchlistItem.from_row(row, active_onboarding_job_id=None),
            job_id=0,
        )

    session.refresh(row)
    return WatchlistCreateResponse(
        data=WatchlistItem.from_row(row, active_onboarding_job_id=job.id),
        job_id=job.id,
    )


@router.delete(
    "/watchlist/{symbol}",
    response_model=OkResponse,
    summary="Remove a ticker from this user's watchlist",
)
def remove_from_watchlist(
    symbol: str,
    user_id: int = Depends(current_user_id),
    repo: WatchlistRepository = Depends(get_watchlist_repository),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    validated = validate_symbol_or_raise(symbol)
    if validated in _SYSTEM_SYMBOLS:
        raise SystemSymbolRemovalError(details={"symbol": validated})

    # Row existence is part of the contract: 404 if we don't find it.
    row = repo.get(user_id=user_id, symbol=validated)
    if row is None:
        raise NotFoundError(details={"symbol": validated})

    # Flip cancel BEFORE deleting the watchlist row so the runner
    # thread's per-day poll reads the flag in time. Already-written
    # daily_price / ticker_snapshot rows stay in the DB — they serve
    # as a gap-fill resume point if the user re-adds the symbol later.
    if row.data_status == STATUS_PENDING:
        job_repo = BackfillJobRepository(session)
        active = job_repo.get_active_onboarding(user_id=user_id, symbol=validated)
        if active is not None:
            job_repo.request_cancel(active.id)
            session.flush()

    repo.remove(user_id=user_id, symbol=validated)
    return OkResponse()


# --- Internal helpers -----------------------------------------------------


async def _preflight_symbol(symbol: str, *, data_source: DataSource) -> None:
    """Lightweight "is this ticker real?" probe.

    Raises :class:`InvalidTickerError` (400) on empty frame — yfinance
    answered, just with no data. Raises
    :class:`PreflightUnavailableError` (503) on
    :class:`DataSourceError` — the provider itself errored, retry is
    appropriate. Timeout exceptions also map to 503.
    """
    import asyncio

    try:
        async with asyncio.timeout(_PREFLIGHT_BUDGET_SECONDS):
            frames = await data_source.bulk_download([symbol], period="5d")
    except TimeoutError as exc:
        raise PreflightUnavailableError(details={"reason": "timeout", "symbol": symbol}) from exc
    except DataSourceError as exc:
        reason = exc.details.get("reason") if isinstance(exc.details, dict) else None
        if reason == "delisted_or_invalid":
            raise InvalidTickerError(details={"symbol": symbol}) from exc
        raise PreflightUnavailableError(
            details={"reason": reason or "upstream_error", "symbol": symbol}
        ) from exc

    frame = frames.get(symbol)
    if frame is None:
        frame = frames.get(symbol.upper())
    if frame is None or frame.empty:
        raise InvalidTickerError(details={"symbol": symbol})

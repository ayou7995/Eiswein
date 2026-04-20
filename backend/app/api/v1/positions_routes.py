"""Positions CRUD + trade log (Phase 5).

Flow summary
------------
* POST /positions         — opens a new position AND records the opening
  buy trade in the same transaction. Rejects if the symbol is not on
  the caller's watchlist (we only track P&L for symbols the system is
  computing indicators for — B3).
* POST /positions/{id}/add    — buy more; recomputes weighted-average
  cost. Serialised on :func:`get_position_lock` so two simultaneous
  adds can't clobber each other's read-modify-write.
* POST /positions/{id}/reduce — sell; computes realized P&L from
  the stored avg_cost (NEVER client-supplied). Auto-closes the
  position when shares reach zero.
* DELETE /positions/{id}  — soft-close; refuses if shares remain.
* GET /positions          — list, with latest close attached so the
  UI can show unrealized P&L without a second round-trip.
* GET /positions/{id}     — single-position detail with last 20 trades.

This module intentionally does NOT use ``from __future__ import
annotations`` — Pydantic response-model + slowapi's decorator need
runtime annotations (watchlist_routes.py has the same note).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.api.dependencies import (
    current_user_id,
    get_audit_repository,
    get_daily_price_repository,
    get_position_repository,
    get_trade_repository,
    get_watchlist_repository,
)
from app.api.v1.watchlist_routes import validate_symbol_or_raise
from app.db.models import Position, Trade
from app.db.repositories.audit_repository import (
    POSITION_ADD,
    POSITION_CLOSED,
    POSITION_OPENED,
    POSITION_REDUCE,
    AuditRepository,
)
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.position_repository import (
    PositionNotFoundError,
    PositionRepository,
)
from app.db.repositories.trade_repository import TradeRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.locks import get_position_lock
from app.security.exceptions import ValidationError as EisweinValidationError
from app.security.rate_limit import limiter

router = APIRouter(tags=["positions"])
logger = structlog.get_logger("eiswein.api.positions")

SideLiteral = Literal["buy", "sell"]

# Wire format for Decimal fields: always 6 decimal places, always a
# string — never a JSON number — so clients don't lose precision in
# JavaScript's float64 representation. See B7.
_DECIMAL_QUANT = Decimal("0.000001")


def _quantize(value: Decimal) -> Decimal:
    # Use default rounding (ROUND_HALF_EVEN) — matches the platform's
    # baked-in Decimal rounding and avoids bias across many trades.
    return value.quantize(_DECIMAL_QUANT)


def _serialize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(_quantize(value))


def _ensure_watchlisted(*, user_id: int, symbol: str, watchlist: WatchlistRepository) -> None:
    if watchlist.get(user_id=user_id, symbol=symbol) is None:
        raise EisweinValidationError(
            details={"reason": "symbol_not_on_watchlist", "symbol": symbol},
        )


class OpenPositionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    shares: Decimal = Field(gt=Decimal(0))
    price: Decimal = Field(gt=Decimal(0))
    executed_at: datetime
    note: str | None = Field(default=None, max_length=500)


class AdjustPositionRequest(BaseModel):
    shares: Decimal = Field(gt=Decimal(0))
    price: Decimal = Field(gt=Decimal(0))
    executed_at: datetime
    note: str | None = Field(default=None, max_length=500)


class TradeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    position_id: int | None
    symbol: str
    side: SideLiteral
    shares: Decimal
    price: Decimal
    executed_at: datetime
    realized_pnl: Decimal | None
    note: str | None
    created_at: datetime

    @field_serializer("shares", "price")
    def _ser_decimal(self, value: Decimal) -> str:
        return str(_quantize(value))

    @field_serializer("realized_pnl")
    def _ser_pnl(self, value: Decimal | None) -> str | None:
        return _serialize_decimal(value)


class PositionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    symbol: str
    shares: Decimal
    avg_cost: Decimal
    opened_at: datetime
    closed_at: datetime | None
    notes: str | None
    # Enriched fields — present for open positions when DailyPrice has a
    # recent close. ``None`` is valid (e.g. data still backfilling).
    current_price: Decimal | None
    unrealized_pnl: Decimal | None

    @field_serializer("shares", "avg_cost")
    def _ser_required(self, value: Decimal) -> str:
        return str(_quantize(value))

    @field_serializer("current_price", "unrealized_pnl")
    def _ser_optional(self, value: Decimal | None) -> str | None:
        return _serialize_decimal(value)


class PositionWithTradesResponse(PositionResponse):
    recent_trades: list[TradeResponse]


class PositionsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[PositionResponse]
    total: int
    has_more: bool = False


class PositionEnvelopeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: PositionResponse


class PositionDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: PositionWithTradesResponse


class OkResponse(BaseModel):
    ok: bool = True


def _enrich(position: Position, *, prices: DailyPriceRepository) -> PositionResponse:
    latest = prices.get_latest(position.symbol)
    if latest is None or position.closed_at is not None:
        current: Decimal | None = None
        unrealized: Decimal | None = None
    else:
        current = Decimal(str(latest.close))
        unrealized = (current - position.avg_cost) * position.shares
    return PositionResponse(
        id=position.id,
        symbol=position.symbol,
        shares=position.shares,
        avg_cost=position.avg_cost,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        notes=position.notes,
        current_price=current,
        unrealized_pnl=unrealized,
    )


def _trade_to_response(trade: Trade) -> TradeResponse:
    side = trade.side if trade.side in ("buy", "sell") else "buy"
    return TradeResponse(
        id=trade.id,
        position_id=trade.position_id,
        symbol=trade.symbol,
        side=side,  # type: ignore[arg-type]  # side column is constrained via CHECK
        shares=trade.shares,
        price=trade.price,
        executed_at=trade.executed_at,
        realized_pnl=trade.realized_pnl,
        note=trade.note,
        created_at=trade.created_at,
    )


def _require_position(*, user_id: int, position_id: int, repo: PositionRepository) -> Position:
    position = repo.get_by_id(user_id=user_id, position_id=position_id)
    if position is None:
        raise PositionNotFoundError(details={"position_id": position_id})
    return position


# --- Routes ---------------------------------------------------------------


@router.get(
    "/positions",
    response_model=PositionsListResponse,
    summary="List caller's positions (open by default)",
)
def list_positions(
    include_closed: int = 0,
    user_id: int = Depends(current_user_id),
    repo: PositionRepository = Depends(get_position_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PositionsListResponse:
    rows = repo.list_all_for_user(user_id) if include_closed else repo.list_open_for_user(user_id)
    data = [_enrich(p, prices=prices) for p in rows]
    return PositionsListResponse(data=data, total=len(data), has_more=False)


@router.post(
    "/positions",
    response_model=PositionEnvelopeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a new position (also records opening buy trade)",
)
@limiter.limit("20/minute")
async def open_position(
    request: Request,
    response: Response,
    payload: OpenPositionRequest,
    user_id: int = Depends(current_user_id),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    positions: PositionRepository = Depends(get_position_repository),
    trades: TradeRepository = Depends(get_trade_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PositionEnvelopeResponse:
    symbol = validate_symbol_or_raise(payload.symbol)
    _ensure_watchlisted(user_id=user_id, symbol=symbol, watchlist=watchlist)

    position = positions.create_open(
        user_id=user_id,
        symbol=symbol,
        shares=payload.shares,
        avg_cost=payload.price,
        opened_at=payload.executed_at,
        notes=payload.note,
    )
    trades.append(
        user_id=user_id,
        position_id=position.id,
        symbol=symbol,
        side="buy",
        shares=payload.shares,
        price=payload.price,
        executed_at=payload.executed_at,
        realized_pnl=None,
        note=payload.note,
    )
    audit.record(
        POSITION_OPENED,
        user_id=user_id,
        ip=_client_ip(request),
        details={
            "position_id": position.id,
            "symbol": symbol,
            "shares": str(_quantize(payload.shares)),
        },
    )
    return PositionEnvelopeResponse(data=_enrich(position, prices=prices))


@router.get(
    "/positions/{position_id}",
    response_model=PositionDetailResponse,
    summary="Single position with recent trades",
)
def get_position(
    position_id: int,
    user_id: int = Depends(current_user_id),
    positions: PositionRepository = Depends(get_position_repository),
    trades: TradeRepository = Depends(get_trade_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PositionDetailResponse:
    position = _require_position(user_id=user_id, position_id=position_id, repo=positions)
    recent = trades.list_for_position(user_id=user_id, position_id=position.id, limit=20)
    enriched = _enrich(position, prices=prices)
    detail = PositionWithTradesResponse(
        id=enriched.id,
        symbol=enriched.symbol,
        shares=enriched.shares,
        avg_cost=enriched.avg_cost,
        opened_at=enriched.opened_at,
        closed_at=enriched.closed_at,
        notes=enriched.notes,
        current_price=enriched.current_price,
        unrealized_pnl=enriched.unrealized_pnl,
        recent_trades=[_trade_to_response(t) for t in recent],
    )
    return PositionDetailResponse(data=detail)


@router.post(
    "/positions/{position_id}/add",
    response_model=PositionEnvelopeResponse,
    summary="Append a buy trade and update weighted-average cost",
)
@limiter.limit("30/minute")
async def add_to_position(
    request: Request,
    response: Response,
    position_id: int,
    payload: AdjustPositionRequest,
    user_id: int = Depends(current_user_id),
    positions: PositionRepository = Depends(get_position_repository),
    trades: TradeRepository = Depends(get_trade_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PositionEnvelopeResponse:
    async with await get_position_lock(position_id):
        position = _require_position(user_id=user_id, position_id=position_id, repo=positions)
        positions.apply_buy(position, shares=payload.shares, price=payload.price)
        trades.append(
            user_id=user_id,
            position_id=position.id,
            symbol=position.symbol,
            side="buy",
            shares=payload.shares,
            price=payload.price,
            executed_at=payload.executed_at,
            realized_pnl=None,
            note=payload.note,
        )
        audit.record(
            POSITION_ADD,
            user_id=user_id,
            ip=_client_ip(request),
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                "shares": str(_quantize(payload.shares)),
            },
        )
        return PositionEnvelopeResponse(data=_enrich(position, prices=prices))


@router.post(
    "/positions/{position_id}/reduce",
    response_model=PositionEnvelopeResponse,
    summary="Append a sell trade; auto-closes when shares hit zero",
)
@limiter.limit("30/minute")
async def reduce_position(
    request: Request,
    response: Response,
    position_id: int,
    payload: AdjustPositionRequest,
    user_id: int = Depends(current_user_id),
    positions: PositionRepository = Depends(get_position_repository),
    trades: TradeRepository = Depends(get_trade_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    prices: DailyPriceRepository = Depends(get_daily_price_repository),
) -> PositionEnvelopeResponse:
    async with await get_position_lock(position_id):
        position = _require_position(user_id=user_id, position_id=position_id, repo=positions)
        realized = positions.apply_sell(position, shares=payload.shares, price=payload.price)
        trades.append(
            user_id=user_id,
            position_id=position.id,
            symbol=position.symbol,
            side="sell",
            shares=payload.shares,
            price=payload.price,
            executed_at=payload.executed_at,
            realized_pnl=realized,
            note=payload.note,
        )
        audit.record(
            POSITION_REDUCE,
            user_id=user_id,
            ip=_client_ip(request),
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                "shares": str(_quantize(payload.shares)),
                "realized_pnl": str(_quantize(realized)),
                "auto_closed": position.closed_at is not None,
            },
        )
        return PositionEnvelopeResponse(data=_enrich(position, prices=prices))


@router.delete(
    "/positions/{position_id}",
    response_model=OkResponse,
    summary="Soft-close an empty position",
)
async def close_position(
    request: Request,
    position_id: int,
    user_id: int = Depends(current_user_id),
    positions: PositionRepository = Depends(get_position_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> OkResponse:
    async with await get_position_lock(position_id):
        position = _require_position(user_id=user_id, position_id=position_id, repo=positions)
        positions.close_if_empty(position)
        audit.record(
            POSITION_CLOSED,
            user_id=user_id,
            ip=_client_ip(request),
            details={"position_id": position.id, "symbol": position.symbol},
        )
        return OkResponse()


# --- Helpers --------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    ip = getattr(request.state, "client_ip", None)
    if isinstance(ip, str) and ip:
        return ip
    return request.client.host if request.client else None


__all__: tuple[str, ...] = ("router",)

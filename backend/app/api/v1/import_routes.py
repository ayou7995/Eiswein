"""Broker trade CSV import (Workstream C).

Endpoints (both ``multipart/form-data`` with ``broker`` + ``file``):

* ``POST /api/v1/import/trades/preview`` — parse + dedup-check only.
  Returns what *would* be imported so the user can review before
  committing. No writes.
* ``POST /api/v1/import/trades/apply`` — re-parses the same file and
  persists through :class:`PositionRepository`. Idempotent via the
  ``(user_id, source, external_id)`` partial unique index — re-running
  on the same CSV reports ``imported=0, skipped_duplicate=N``.

Safety rails
------------
* ``5/minute`` rate limit keyed by the CF-validated client IP.
* 5 MB upload cap checked at buffer time (``UploadFile.size`` when
  available, otherwise a hard cap during ``read``).
* Allowed content types: ``text/csv``, ``application/vnd.ms-excel``
  (Excel's default for plain CSV), ``application/csv``, ``text/plain``
  (Robinhood's exports sometimes carry the loose mime).
* Pydantic schemas at both request (the form fields) and response
  boundary. ``Decimal`` fields serialize as strings to preserve
  precision on the wire (rule 18, same pattern as positions_routes).

This module intentionally does NOT use ``from __future__ import
annotations`` — slowapi's decorator wrapper needs the runtime
annotations resolvable (same note as ``positions_routes.py``).
"""

import io
from datetime import datetime
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_db_session,
    get_position_repository,
    get_trade_repository,
)
from app.db.repositories.position_repository import PositionRepository
from app.db.repositories.trade_repository import TradeRepository
from app.ingestion.importers import IMPORTERS, SUPPORTED_BROKERS
from app.ingestion.importers.base import ImportIssue, TradeImportRecord
from app.security.exceptions import ValidationError as EisweinValidationError
from app.security.rate_limit import limiter
from app.services.trade_import_service import (
    ApplyResult,
    ImportSummary,
    PreviewResult,
    TradeImportService,
    UnknownBrokerError,
)

router = APIRouter(prefix="/import", tags=["import"])
logger = structlog.get_logger("eiswein.api.import")

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — ≈30k CSV rows, safe headroom

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",
        "application/octet-stream",
    }
)


# --- Pydantic schemas (response) ------------------------------------------


class TradeRecordSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Literal["buy", "sell"]
    shares: Decimal
    price: Decimal
    executed_at: datetime
    external_id: str
    source: str
    note: str | None = None

    @field_serializer("shares", "price")
    def _ser_decimal(self, value: Decimal) -> str:
        return str(value)


class ImportIssueSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_index: int
    severity: Literal["warn", "error"]
    code: str
    message: str


class ImportSummarySchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    would_import: int
    would_skip_duplicate: int
    warnings: int
    errors: int
    imported: int = 0
    skipped_duplicate: int = 0


class PreviewRowSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    record: TradeRecordSchema
    action: Literal["import", "skip_duplicate", "warn", "error"]
    issues: list[ImportIssueSchema]


class PreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker: str
    total_rows: int
    parsed: list[PreviewRowSchema]
    file_issues: list[ImportIssueSchema]
    summary: ImportSummarySchema


class ApplyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker: str
    summary: ImportSummarySchema
    issues: list[ImportIssueSchema]


class BrokerOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str


class BrokersResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    brokers: list[BrokerOption]


# --- Helpers --------------------------------------------------------------


def _to_record_schema(r: TradeImportRecord) -> TradeRecordSchema:
    return TradeRecordSchema(
        symbol=r.symbol,
        side=r.side,
        shares=r.shares,
        price=r.price,
        executed_at=r.executed_at,
        external_id=r.external_id,
        source=r.source,
        note=r.note,
    )


def _to_issue_schema(i: ImportIssue) -> ImportIssueSchema:
    return ImportIssueSchema(
        row_index=i.row_index,
        severity=i.severity,
        code=i.code,
        message=i.message,
    )


def _to_summary_schema(s: ImportSummary) -> ImportSummarySchema:
    return ImportSummarySchema(
        would_import=s.would_import,
        would_skip_duplicate=s.would_skip_duplicate,
        warnings=s.warnings,
        errors=s.errors,
        imported=s.imported,
        skipped_duplicate=s.skipped_duplicate,
    )


def _to_preview_response(result: PreviewResult) -> PreviewResponse:
    return PreviewResponse(
        broker=result.broker,
        total_rows=result.total_rows,
        parsed=[
            PreviewRowSchema(
                record=_to_record_schema(row.record),
                action=row.action,
                issues=[_to_issue_schema(i) for i in row.issues],
            )
            for row in result.parsed
        ],
        file_issues=[_to_issue_schema(i) for i in result.file_issues],
        summary=_to_summary_schema(result.summary),
    )


def _to_apply_response(result: ApplyResult) -> ApplyResponse:
    return ApplyResponse(
        broker=result.broker,
        summary=_to_summary_schema(result.summary),
        issues=[_to_issue_schema(i) for i in result.issues],
    )


async def _read_upload(file: UploadFile) -> bytes:
    """Buffer the upload with a hard size cap.

    ``UploadFile.size`` is the multipart-declared size (may be None for
    streamed uploads). We always re-check by reading up to
    ``_MAX_UPLOAD_BYTES + 1`` and raising 413 if the ceiling was hit.
    """
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"檔案超過上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"檔案超過上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    return data


def _validate_broker(broker: str) -> str:
    key = broker.strip().lower()
    if key not in IMPORTERS:
        raise EisweinValidationError(
            details={"reason": "unknown_broker", "broker": broker},
        )
    return key


def _validate_content_type(file: UploadFile) -> None:
    # Content type header can be absent (some clients) or vendor-
    # specific. When present, reject clearly wrong types so we don't
    # try to parse a PDF or image as CSV.
    ctype = (file.content_type or "").split(";", 1)[0].strip().lower()
    if ctype and ctype not in _ALLOWED_CONTENT_TYPES:
        raise EisweinValidationError(
            details={"reason": "unsupported_content_type", "content_type": ctype},
        )


def _build_service(
    db: Session,
    trades: TradeRepository,
    positions: PositionRepository,
) -> TradeImportService:
    return TradeImportService(
        db=db,
        trade_repository=trades,
        position_repository=positions,
    )


# --- Routes ---------------------------------------------------------------


@router.get(
    "/brokers",
    response_model=BrokersResponse,
    summary="List supported brokers for the trade-import dropdown",
)
def list_brokers(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
) -> BrokersResponse:
    # Static at boot — auth-gated only because it is part of the import
    # surface, not because the list itself is sensitive.
    return BrokersResponse(
        brokers=[BrokerOption(key=k, label=label) for k, label in SUPPORTED_BROKERS]
    )


@router.post(
    "/trades/preview",
    response_model=PreviewResponse,
    summary="Parse a broker CSV and show what would be imported (no writes)",
)
@limiter.limit("5/minute")
async def preview_trades(
    request: Request,
    response: Response,
    broker: str = Form(..., max_length=32),
    file: UploadFile = File(...),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db_session),
    trades: TradeRepository = Depends(get_trade_repository),
    positions: PositionRepository = Depends(get_position_repository),
) -> PreviewResponse:
    broker_key = _validate_broker(broker)
    _validate_content_type(file)
    raw = await _read_upload(file)
    service = _build_service(db, trades, positions)
    try:
        result = service.preview(
            user_id=user_id,
            broker_key=broker_key,
            file=io.BytesIO(raw),
        )
    except UnknownBrokerError as exc:  # pragma: no cover — _validate_broker catches first
        raise EisweinValidationError(
            details={"reason": "unknown_broker", "broker": str(exc)},
        ) from exc
    # Log counts only — never symbols, never prices (rule 15 / PII).
    logger.info(
        "trade_import_preview",
        user_id=user_id,
        broker=broker_key,
        total_rows=result.total_rows,
        would_import=result.summary.would_import,
        would_skip_duplicate=result.summary.would_skip_duplicate,
        errors=result.summary.errors,
    )
    return _to_preview_response(result)


@router.post(
    "/trades/apply",
    response_model=ApplyResponse,
    summary="Persist a broker CSV through PositionRepository (idempotent)",
)
@limiter.limit("5/minute")
async def apply_trades(
    request: Request,
    response: Response,
    broker: str = Form(..., max_length=32),
    file: UploadFile = File(...),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db_session),
    trades: TradeRepository = Depends(get_trade_repository),
    positions: PositionRepository = Depends(get_position_repository),
) -> ApplyResponse:
    broker_key = _validate_broker(broker)
    _validate_content_type(file)
    raw = await _read_upload(file)
    service = _build_service(db, trades, positions)
    try:
        result = service.apply(
            user_id=user_id,
            broker_key=broker_key,
            file=io.BytesIO(raw),
        )
    except UnknownBrokerError as exc:  # pragma: no cover — _validate_broker catches first
        raise EisweinValidationError(
            details={"reason": "unknown_broker", "broker": str(exc)},
        ) from exc
    # The session is committed by get_db_session on clean return; each
    # record already lives in its own savepoint so partial failure
    # still persists the good rows.
    logger.info(
        "trade_import_apply",
        user_id=user_id,
        broker=broker_key,
        imported=result.summary.imported,
        skipped_duplicate=result.summary.skipped_duplicate,
        errors=result.summary.errors,
    )
    return _to_apply_response(result)


__all__: tuple[str, ...] = ("router",)

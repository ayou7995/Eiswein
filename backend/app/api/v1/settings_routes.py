"""Settings endpoints (Phase 5).

* POST   /settings/password      — change password. Validates current,
  enforces strength policy on the new one, records an AuditLog entry.
* GET    /settings/audit-log     — caller's own audit history; never
  leaks another user's events.
* GET    /settings/system-info   — db size + counts + last-refresh
  timestamps for the diagnostics page.
* POST   /settings/data-refresh  — synchronous manual ``daily_update``.
  Rate-limited (1/hour/ip) so a click-happy user can't kick off 100
  yfinance bulk downloads.
"""

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_audit_repository,
    get_data_source_dep,
    get_db_session,
    get_position_repository,
    get_settings_dep,
    get_trade_repository,
    get_user_repository,
    get_watchlist_repository,
)
from app.config import Settings
from app.datasources.base import DataSource
from app.db.repositories.audit_repository import (
    MANUAL_DATA_REFRESH,
    PASSWORD_CHANGED,
    AuditRepository,
)
from app.db.repositories.position_repository import PositionRepository
from app.db.repositories.system_metadata_repository import (
    KEY_LAST_BACKUP_AT,
    KEY_LAST_DAILY_UPDATE_AT,
    SystemMetadataRepository,
)
from app.db.repositories.trade_repository import TradeRepository
from app.db.repositories.user_repository import UserRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.daily_ingestion import run_daily_update
from app.security.auth import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.security.exceptions import InvalidCredentialsError
from app.security.rate_limit import limiter

router = APIRouter(tags=["settings"])
logger = structlog.get_logger("eiswein.api.settings")


# --- password change ------------------------------------------------------


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class PasswordChangeResponse(BaseModel):
    ok: bool = True


@router.post(
    "/settings/password",
    response_model=PasswordChangeResponse,
    summary="Change caller's password (requires current password)",
)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    response: Response,
    payload: PasswordChangeRequest,
    user_id: int = Depends(current_user_id),
    users: UserRepository = Depends(get_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
) -> PasswordChangeResponse:
    user = users.by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidCredentialsError()
    if not verify_password(payload.current_password, user.password_hash):
        audit.record(
            PASSWORD_CHANGED,
            user_id=user_id,
            ip=_client_ip(request),
            details={"outcome": "wrong_current"},
        )
        raise InvalidCredentialsError()

    # zxcvbn penalises passwords containing the username / email.
    user_inputs = [user.username]
    if user.email:
        user_inputs.append(user.email)
    validate_password_strength(payload.new_password, user_inputs=user_inputs)

    users.update_password(user, hash_password(payload.new_password))
    audit.record(
        PASSWORD_CHANGED,
        user_id=user_id,
        ip=_client_ip(request),
        details={"outcome": "ok"},
    )
    return PasswordChangeResponse()


# --- audit log ------------------------------------------------------------


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    timestamp: datetime
    event_type: str
    ip: str | None
    details: dict[str, Any]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[AuditEntryResponse]
    total: int
    has_more: bool = False


_AUDIT_DETAIL_REDACT_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "token",
        "secret",
        "refresh_token",
        "access_token",
    }
)


def _sanitize_details(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Strip any fields that could leak secrets.

    Belt-and-suspenders: none of our audit writes include these fields,
    but if a future code path ever does, this keeps the API from
    surfacing them to the client. Values are replaced with
    ``"[redacted]"`` so the field's presence is still visible for
    debugging.
    """
    if not raw:
        return {}
    safe: dict[str, Any] = {}
    for k, v in raw.items():
        if k.lower() in _AUDIT_DETAIL_REDACT_KEYS:
            safe[k] = "[redacted]"
        else:
            safe[k] = v
    return safe


@router.get(
    "/settings/audit-log",
    response_model=AuditLogResponse,
    summary="Caller's audit log entries (most recent first)",
)
def list_audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    user_id: int = Depends(current_user_id),
    audit: AuditRepository = Depends(get_audit_repository),
) -> AuditLogResponse:
    rows = audit.list_for_user(user_id=user_id, limit=limit)
    data = [
        AuditEntryResponse(
            id=row.id,
            timestamp=row.timestamp,
            event_type=row.event_type,
            ip=row.ip,
            details=_sanitize_details(row.details),
        )
        for row in rows
    ]
    return AuditLogResponse(data=data, total=len(data), has_more=False)


# --- system-info ----------------------------------------------------------


class SystemInfoResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    db_size_bytes: int | None
    last_daily_update_at: datetime | None
    last_backup_at: datetime | None
    watchlist_count: int
    positions_count: int
    trade_count: int
    user_count: int | None


# Simple per-process 30s cache. Protected by a small tuple (last_ts,
# response) — tests reset it via ``_clear_system_info_cache``.
_SYSTEM_INFO_CACHE_TTL_SECONDS = 30.0
_system_info_cache: tuple[float, SystemInfoResponse] | None = None


def _clear_system_info_cache() -> None:
    global _system_info_cache
    _system_info_cache = None


def _db_size_bytes(engine_url: str) -> int | None:
    # Only report the on-disk size for file-backed SQLite; ``:memory:``
    # returns None so tests don't flap on filesystem inspection.
    prefix = "sqlite:///"
    if not engine_url.startswith(prefix):
        return None
    path_str = engine_url[len(prefix) :]
    if path_str.startswith(":memory:"):
        return None
    path = Path(path_str)
    try:
        return path.stat().st_size
    except OSError:
        return None


@router.get(
    "/settings/system-info",
    response_model=SystemInfoResponse,
    summary="Read-only diagnostics snapshot (30s cache)",
)
def system_info(
    user_id: int = Depends(current_user_id),
    users: UserRepository = Depends(get_user_repository),
    watchlist: WatchlistRepository = Depends(get_watchlist_repository),
    positions: PositionRepository = Depends(get_position_repository),
    trades: TradeRepository = Depends(get_trade_repository),
    settings: Settings = Depends(get_settings_dep),
    session: Session = Depends(get_db_session),
) -> SystemInfoResponse:
    global _system_info_cache
    now = time.monotonic()
    if _system_info_cache is not None:
        last_ts, cached = _system_info_cache
        if now - last_ts < _SYSTEM_INFO_CACHE_TTL_SECONDS:
            return cached

    caller = users.by_id(user_id)
    is_admin = bool(caller and caller.is_admin)

    # Phase 6 jobs record their own run timestamps in system_metadata —
    # prefer those over the old "most-recent Watchlist.last_refresh_at"
    # proxy. Fall back to that proxy when the key is unset (pre-Phase 6
    # deploys, fresh DB).
    from app.db.models import Watchlist

    metadata = SystemMetadataRepository(session)
    last_update_at = metadata.get_datetime(KEY_LAST_DAILY_UPDATE_AT)
    if last_update_at is None:
        last_update_at = session.execute(select(func.max(Watchlist.last_refresh_at))).scalar_one()
    last_backup_at = metadata.get_datetime(KEY_LAST_BACKUP_AT)

    wl_count = session.execute(select(func.count(Watchlist.id))).scalar_one()

    response = SystemInfoResponse(
        db_size_bytes=_db_size_bytes(settings.database_url),
        last_daily_update_at=last_update_at,
        last_backup_at=last_backup_at,
        watchlist_count=int(wl_count),
        positions_count=positions.count_for_user(user_id, include_closed=True),
        trade_count=trades.count_for_user(user_id),
        # Keep non-admin users from seeing aggregate user counts; v1 is
        # single-admin anyway, but the shape should be correct.
        user_count=users.count() if is_admin else None,
    )
    _system_info_cache = (now, response)
    return response


# --- manual data refresh --------------------------------------------------


class DataRefreshResponse(BaseModel):
    ok: bool = True
    job_id: str
    started_at: datetime
    market_open: bool
    # Workstream B: gap-fill counts so the frontend can render the
    # "filled N rows across M symbols" success banner in zh-TW.
    gaps_filled_rows: int = 0
    gaps_filled_symbols: int = 0


@router.post(
    "/settings/data-refresh",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataRefreshResponse,
    summary="Manually trigger the daily_update job (rate-limited)",
)
@limiter.limit("1/hour")
async def data_refresh(
    request: Request,
    response: Response,
    _background: BackgroundTasks,
    user_id: int = Depends(current_user_id),
    audit: AuditRepository = Depends(get_audit_repository),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    data_source: DataSource = Depends(get_data_source_dep),
) -> DataRefreshResponse:
    # v1: run synchronously. If >10s, warn but do not time out — the
    # browser's fetch can sit on the connection. Phase 6 will route
    # this through a scheduler queue.
    job_id = uuid.uuid4().hex
    started_at = _server_now()
    logger.info("manual_data_refresh_start", user_id=user_id, job_id=job_id)

    result = await run_daily_update(
        db=session,
        data_source=data_source,
        settings=settings,
        trigger="manual",
    )
    duration = (_server_now() - started_at).total_seconds()
    if duration > 10.0:
        logger.warning(
            "manual_data_refresh_slow",
            job_id=job_id,
            duration_seconds=round(duration, 2),
        )

    audit.record(
        MANUAL_DATA_REFRESH,
        user_id=user_id,
        ip=_client_ip(request),
        details={
            "job_id": job_id,
            "market_open": result.market_open,
            "symbols_requested": result.symbols_requested,
            "symbols_succeeded": result.symbols_succeeded,
            "symbols_failed": result.symbols_failed,
            "gaps_filled_rows": result.gaps_filled_rows,
            "gaps_filled_symbols": result.gaps_filled_symbols,
            "duration_seconds": round(duration, 3),
        },
    )

    return DataRefreshResponse(
        job_id=job_id,
        started_at=started_at,
        market_open=result.market_open,
        gaps_filled_rows=result.gaps_filled_rows,
        gaps_filled_symbols=result.gaps_filled_symbols,
    )


# --- helpers --------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    ip = getattr(request.state, "client_ip", None)
    if isinstance(ip, str) and ip:
        return ip
    return request.client.host if request.client else None


def _server_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


# Re-exported for tests that want to reset the system-info cache
# between test cases.
__all__: tuple[str, ...] = (
    "_clear_system_info_cache",
    "router",
)

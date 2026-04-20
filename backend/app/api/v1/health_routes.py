"""Healthcheck endpoint (I23).

Phase 6 wires the scheduler + data-source status through this route so
Cloudflare's uptime probe (and the local dev /health fetch) actually
reflect runtime state. ``status`` is ``"degraded"`` whenever any
subsystem is in an ``error`` state; ``not_configured`` does not
degrade health (it's informational — e.g. Schwab is simply not wired
up yet).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session, get_settings_dep
from app.config import Settings
from app.jobs.scheduler import SchedulerHandle, get_scheduler_status

router = APIRouter(tags=["health"])


SubsystemState = Literal["ok", "degraded", "not_configured", "error"]


class SubsystemStatus(BaseModel):
    status: SubsystemState


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: SubsystemStatus
    scheduler: SubsystemStatus
    data_sources: dict[str, SubsystemState]


@router.get("/health", response_model=HealthResponse, summary="System health")
def read_health(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        db = SubsystemStatus(status="ok")
    except SQLAlchemyError:
        db = SubsystemStatus(status="error")

    handle: SchedulerHandle | None = getattr(request.app.state, "scheduler_handle", None)
    raw_state = get_scheduler_status(handle).status
    # Map scheduler's "running" / "not_started" / "error" vocabulary
    # onto the SubsystemStatus literal. "not_started" is displayed as
    # "not_configured" on the health endpoint — the two mean the same
    # thing for the operator (scheduler is not actively running, no
    # error was raised to get there).
    scheduler_state: SubsystemState
    if raw_state == "running":
        scheduler_state = "ok"
    elif raw_state == "error":
        scheduler_state = "error"
    else:
        scheduler_state = "not_configured"
    scheduler = SubsystemStatus(status=scheduler_state)

    data_sources: dict[str, SubsystemState] = {
        "yfinance": "ok",  # yfinance has no API key — always "configured".
        "fred": (
            "ok"
            if settings.fred_api_key is not None and settings.fred_api_key.get_secret_value()
            else "not_configured"
        ),
        "schwab": "not_configured",  # Schwab integration lands post-Phase 6.
    }

    overall: Literal["ok", "degraded"] = "ok"
    if db.status == "error" or scheduler_state == "error":
        overall = "degraded"

    return HealthResponse(
        status=overall,
        db=db,
        scheduler=scheduler,
        data_sources=data_sources,
    )

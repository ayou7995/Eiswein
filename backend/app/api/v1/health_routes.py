"""Healthcheck endpoint (I23)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session

router = APIRouter(tags=["health"])


class SubsystemStatus(BaseModel):
    status: Literal["ok", "degraded", "not_configured", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: SubsystemStatus
    scheduler: SubsystemStatus
    data_sources: dict[str, Literal["ok", "degraded", "not_configured", "error"]]


@router.get("/health", response_model=HealthResponse, summary="System health")
def read_health(session: Session = Depends(get_db_session)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        db = SubsystemStatus(status="ok")
    except SQLAlchemyError:
        db = SubsystemStatus(status="error")
    # Scheduler + data sources wire up in Phase 1/6; Phase 0 reports
    # the "not_configured" placeholder so the healthcheck shape is
    # stable from day one.
    return HealthResponse(
        status="ok" if db.status == "ok" else "degraded",
        db=db,
        scheduler=SubsystemStatus(status="not_configured"),
        data_sources={
            "yfinance": "not_configured",
            "fred": "not_configured",
            "schwab": "not_configured",
        },
    )

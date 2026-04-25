"""Indicator drift detection + revalidation trigger (Phase 1 UX overhaul).

The user should never need to think about "backfill". When we bump
``INDICATOR_VERSION`` in ``app.indicators.base`` any row computed under
the old rules is stale. This module exposes two endpoints the dashboard
polls + clicks:

* ``GET  /api/v1/indicators/drift``     — "is there stale data?"
* ``POST /api/v1/indicators/revalidate`` — "recompute everything"

The heavy lifting is in :class:`BackfillService.revalidate_all_snapshots`;
this file is pure HTTP glue.

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
slowapi's ``@limiter.limit`` decorator captures the endpoint signature
at import time and forward references under PEP 563 postponed
evaluation fail to resolve in its wrapper's ``__globals__`` — same
reason as ``auth_routes.py`` / ``admin_routes.py``.
"""

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import current_user_id, get_db_session, get_settings_dep
from app.config import Settings
from app.db.models import BackfillJob, TickerSnapshot
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.indicators.base import INDICATOR_VERSION
from app.security.rate_limit import limiter
from app.services.backfill_service import BackfillService

router = APIRouter(tags=["indicators"])
logger = structlog.get_logger("eiswein.api.indicators")


class IndicatorDriftResponse(BaseModel):
    """Summary of version drift across persisted ticker snapshots.

    ``has_drift`` is the scalar the UI keys off: when True, render the
    "indicator formulas changed — click to recompute" banner. When
    ``running_revalidation_job_id`` is set, the UI switches to a
    progress indicator instead of the recompute button.
    """

    model_config = ConfigDict(frozen=True)

    has_drift: bool
    current_version: str
    stale_versions: list[str]
    stale_row_count: int
    running_revalidation_job_id: int | None


class RevalidateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: int
    state: str


@router.get(
    "/indicators/drift",
    response_model=IndicatorDriftResponse,
    summary="Detect ticker_snapshot rows computed under older INDICATOR_VERSION",
)
@limiter.limit("60/minute")
async def get_indicator_drift(
    request: Request,
    response: Response,
    _user_id: int = Depends(current_user_id),
    session: Session = Depends(get_db_session),
) -> IndicatorDriftResponse:
    """Return the drift summary.

    Single GROUP BY over ``ticker_snapshot.indicator_version`` — O(rows
    in table) without an index, cheap enough for a 60/min poll given
    realistic watchlist sizes (<100 symbols * 2 years trading days ≈
    50k rows). If history grows we'd add a partial index on
    ``indicator_version != current_version``.
    """
    current = INDICATOR_VERSION
    stmt = select(TickerSnapshot.indicator_version, func.count()).group_by(
        TickerSnapshot.indicator_version
    )
    rows = session.execute(stmt).all()

    stale_versions: list[str] = []
    stale_row_count = 0
    for version, count in rows:
        if version != current:
            stale_versions.append(str(version))
            stale_row_count += int(count)

    # Report an in-flight revalidation so the UI doesn't nag the user
    # to re-run while one is already progressing.
    running_job_id: int | None = None
    active = BackfillJobRepository(session).get_active()
    if active is not None and active.kind == "revalidation":
        running_job_id = active.id

    return IndicatorDriftResponse(
        has_drift=bool(stale_versions),
        current_version=current,
        stale_versions=sorted(stale_versions),
        stale_row_count=stale_row_count,
        running_revalidation_job_id=running_job_id,
    )


@router.post(
    "/indicators/revalidate",
    response_model=RevalidateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Re-run indicators + snapshots for every trading day",
)
@limiter.limit("5/minute")
async def revalidate_indicators(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    settings: Settings = Depends(get_settings_dep),
) -> RevalidateResponse:
    """Kick off a full-history revalidation job.

    409 ``backfill_already_running`` when another job (onboarding or
    revalidation) is already in flight — the BackfillService's
    ``get_active`` guard handles that; the global error handler maps
    the exception to the HTTP response.
    """
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    run_inline = bool(getattr(request.app.state, "backfill_run_inline", False))
    service = BackfillService(
        session_factory=session_factory,
        settings=settings,
        run_inline=run_inline,
    )
    job: BackfillJob = service.revalidate_all_snapshots(user_id=user_id)
    return RevalidateResponse(job_id=job.id, state=job.state)


__all__ = ("router",)

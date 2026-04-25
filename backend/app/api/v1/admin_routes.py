"""Generic job status + cancel endpoints (Phase 1 UX overhaul).

Two routes, both under ``/api/v1/jobs``:

* ``GET  /jobs/{job_id}``          — poll state + progress counters
* ``POST /jobs/{job_id}/cancel``   — request cooperative cancellation

"Backfill" is gone as a user concept. Both job kinds
(``onboarding`` and ``revalidation``) share the :class:`BackfillJob`
table and therefore this polling surface. The concrete jobs are
created by:

* :class:`SymbolOnboardingService` — fired by ``POST /watchlist``
* :class:`BackfillService` — fired by ``POST /indicators/revalidate``

Auth: every route requires a valid session cookie (``current_user_id``).

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
Same slowapi + FastAPI forward-reference caveat as the other routers.
"""

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import current_user_id, get_db_session
from app.db.models import BackfillJob
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.security.exceptions import NotFoundError
from app.security.rate_limit import limiter

router = APIRouter(tags=["jobs"])
logger = structlog.get_logger("eiswein.api.jobs")


class JobResponse(BaseModel):
    """Full :class:`BackfillJob` projection — the polling shape."""

    model_config = ConfigDict(frozen=True)

    id: int
    kind: str
    symbol: str | None
    from_date: str
    to_date: str
    state: str
    force: bool
    processed_days: int
    total_days: int
    skipped_existing_days: int
    failed_days: int
    started_at: str | None
    finished_at: str | None
    error: str | None
    created_at: str
    created_by_user_id: int
    cancel_requested: bool


def _job_to_response(job: BackfillJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        kind=job.kind,
        symbol=job.symbol,
        from_date=job.from_date.isoformat(),
        to_date=job.to_date.isoformat(),
        state=job.state,
        force=job.force,
        processed_days=job.processed_days,
        total_days=job.total_days,
        skipped_existing_days=job.skipped_existing_days,
        failed_days=job.failed_days,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=job.error,
        created_at=job.created_at.isoformat(),
        created_by_user_id=job.created_by_user_id,
        cancel_requested=job.cancel_requested,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Poll the state + progress counters of a job",
)
@limiter.limit("120/minute")
async def get_job(
    request: Request,
    response: Response,
    job_id: int,
    _user_id: int = Depends(current_user_id),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    repo = BackfillJobRepository(session)
    job = repo.get(job_id)
    if job is None:
        raise NotFoundError(details={"job_id": job_id})
    return _job_to_response(job)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request cooperative cancellation of a running job",
)
@limiter.limit("10/minute")
async def cancel_job(
    request: Request,
    response: Response,
    job_id: int,
    _user_id: int = Depends(current_user_id),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    repo = BackfillJobRepository(session)
    job = repo.get(job_id)
    if job is None:
        raise NotFoundError(details={"job_id": job_id})
    # Idempotent on terminal jobs — flipping the flag on a completed
    # row is a no-op (the runner thread is gone) but keeps the HTTP
    # contract simple: always 202.
    if job.state in {"completed", "cancelled", "failed"}:
        return _job_to_response(job)
    job = repo.request_cancel(job_id)
    return _job_to_response(job)


__all__: tuple[str, ...] = ("router",)

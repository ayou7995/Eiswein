"""Watchlist group CRUD endpoints (Phase B — commit B).

Routes:

* ``GET    /api/v1/watchlist/groups``            — list user's groups
* ``POST   /api/v1/watchlist/groups``            — create new group
* ``PATCH  /api/v1/watchlist/groups/{group_id}`` — rename a group
* ``DELETE /api/v1/watchlist/groups/{group_id}`` — delete a group
* ``PATCH  /api/v1/watchlist/groups/reorder``    — reorder groups
* ``PATCH  /api/v1/watchlist/{symbol}/group``    — move ticker to group

Every route requires auth via :func:`current_user_id`. Rate limit is
``60/minute`` per CF-Connecting-IP — group management is a UI-driven
operation, not a polling surface.

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
Same slowapi + FastAPI forward-reference caveat as the other routers.
"""

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_db_session,
    get_watchlist_group_repository,
    get_watchlist_repository,
)
from app.db.repositories.watchlist_group_repository import WatchlistGroupRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.security.exceptions import NotFoundError
from app.security.rate_limit import limiter

router = APIRouter(tags=["watchlist-groups"])
logger = structlog.get_logger("eiswein.api.watchlist_groups")


# --- Pydantic models ------------------------------------------------------


class GroupOut(BaseModel):
    """Single group projection. ``symbol_count`` is denormalized so the
    sidebar can render `(N)` without a second round-trip."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    position: int
    symbol_count: int


class GroupListResponse(BaseModel):
    data: list[GroupOut]
    total: int


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class GroupRenameRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)


class GroupReorderRequest(BaseModel):
    ordered_ids: list[int] = Field(min_length=1, max_length=64)


class WatchlistGroupAssignmentRequest(BaseModel):
    group_id: int | None = None


class OkResponse(BaseModel):
    ok: bool = True


# --- helpers --------------------------------------------------------------


def _group_to_out(
    *,
    group_id: int,
    name: str,
    position: int,
    counts: dict[int, int],
) -> GroupOut:
    return GroupOut(
        id=group_id,
        name=name,
        position=position,
        symbol_count=counts.get(group_id, 0),
    )


# --- routes ---------------------------------------------------------------


@router.get(
    "/watchlist/groups",
    response_model=GroupListResponse,
    summary="List this user's watchlist groups",
)
@limiter.limit("60/minute")
async def list_groups(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
) -> GroupListResponse:
    rows = list(repo.list_for_user(user_id))
    counts = repo.count_symbols_per_group(user_id)
    items = [
        _group_to_out(
            group_id=row.id,
            name=row.name,
            position=row.position,
            counts=counts,
        )
        for row in rows
    ]
    return GroupListResponse(data=items, total=len(items))


@router.post(
    "/watchlist/groups",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new watchlist group",
)
@limiter.limit("60/minute")
async def create_group(
    request: Request,
    response: Response,
    payload: GroupCreateRequest,
    user_id: int = Depends(current_user_id),
    repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
) -> GroupOut:
    row = repo.create(user_id=user_id, name=payload.name)
    counts = repo.count_symbols_per_group(user_id)
    return _group_to_out(
        group_id=row.id, name=row.name, position=row.position, counts=counts
    )


@router.patch(
    "/watchlist/groups/reorder",
    response_model=OkResponse,
    summary="Reorder this user's watchlist groups",
)
@limiter.limit("60/minute")
async def reorder_groups(
    request: Request,
    response: Response,
    payload: GroupReorderRequest,
    user_id: int = Depends(current_user_id),
    repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
) -> OkResponse:
    repo.reorder(user_id=user_id, ordered_group_ids=list(payload.ordered_ids))
    return OkResponse()


@router.patch(
    "/watchlist/groups/{group_id}",
    response_model=GroupOut,
    summary="Rename a watchlist group",
)
@limiter.limit("60/minute")
async def rename_group(
    request: Request,
    response: Response,
    group_id: int,
    payload: GroupRenameRequest,
    user_id: int = Depends(current_user_id),
    repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
) -> GroupOut:
    if payload.name is None:
        # PATCH with no fields is a no-op fetch. Returning current state
        # keeps the API contract symmetric with the rename path.
        row = repo.get(user_id=user_id, group_id=group_id)
        if row is None:
            raise NotFoundError(details={"group_id": group_id})
    else:
        row = repo.rename(user_id=user_id, group_id=group_id, new_name=payload.name)
    counts = repo.count_symbols_per_group(user_id)
    return _group_to_out(
        group_id=row.id, name=row.name, position=row.position, counts=counts
    )


@router.delete(
    "/watchlist/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a watchlist group (orphans set group_id=NULL)",
)
@limiter.limit("60/minute")
async def delete_group(
    request: Request,
    response: Response,
    group_id: int,
    user_id: int = Depends(current_user_id),
    repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
) -> Response:
    repo.delete(user_id=user_id, group_id=group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/watchlist/{symbol}/group",
    response_model=OkResponse,
    summary="Move a watchlist row into a group (or unassign)",
)
@limiter.limit("60/minute")
async def set_watchlist_group(
    request: Request,
    response: Response,
    symbol: str,
    payload: WatchlistGroupAssignmentRequest,
    user_id: int = Depends(current_user_id),
    watchlist_repo: WatchlistRepository = Depends(get_watchlist_repository),
    group_repo: WatchlistGroupRepository = Depends(get_watchlist_group_repository),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    # Symbol validation reuses the watchlist module's regex via
    # validate_symbol_or_raise — kept local-only to avoid a circular
    # import (watchlist_routes imports from us indirectly through
    # __init__.py).
    from app.api.v1.watchlist_routes import validate_symbol_or_raise

    validated = validate_symbol_or_raise(symbol)
    row = watchlist_repo.get(user_id=user_id, symbol=validated)
    if row is None:
        raise NotFoundError(details={"symbol": validated})

    if payload.group_id is not None:
        target = group_repo.get(user_id=user_id, group_id=payload.group_id)
        if target is None:
            raise NotFoundError(details={"group_id": payload.group_id})
        row.group_id = target.id
    else:
        row.group_id = None
    session.flush()
    return OkResponse()

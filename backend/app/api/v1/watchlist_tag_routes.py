"""Watchlist tag CRUD + attach/detach endpoints (Phase B — commit B).

Routes:

* ``GET    /api/v1/watchlist/tags``                    — list user's tags
* ``POST   /api/v1/watchlist/tags``                    — create new tag
* ``PATCH  /api/v1/watchlist/tags/{tag_id}``           — rename and/or recolor
* ``DELETE /api/v1/watchlist/tags/{tag_id}``           — delete a tag
* ``POST   /api/v1/watchlist/{symbol}/tags/{tag_id}``  — attach tag to ticker
* ``DELETE /api/v1/watchlist/{symbol}/tags/{tag_id}``  — detach tag from ticker

Auth: every route requires :func:`current_user_id`. Rate limit
``60/minute`` per CF-Connecting-IP.

Module note — no ``from __future__ import annotations``
-------------------------------------------------------
slowapi's ``@limiter.limit`` captures the endpoint signature at import
time; PEP 563 postponed evaluation breaks its wrapper's forward-ref
resolution. Same caveat as the other v1 routers.
"""

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    current_user_id,
    get_db_session,
    get_watchlist_repository,
    get_watchlist_tag_repository,
)
from app.db.models import WatchlistTag
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.db.repositories.watchlist_tag_repository import WatchlistTagRepository
from app.security.exceptions import NotFoundError
from app.security.rate_limit import limiter

router = APIRouter(tags=["watchlist-tags"])
logger = structlog.get_logger("eiswein.api.watchlist_tags")


# --- Pydantic models ------------------------------------------------------


class TagOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    color: str


class TagListResponse(BaseModel):
    data: list[TagOut]
    total: int
    popular: list[TagOut]


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    color: str = Field(min_length=7, max_length=7)


class TagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = Field(default=None, min_length=7, max_length=7)


class OkResponse(BaseModel):
    ok: bool = True


def _tag_to_out(tag: WatchlistTag) -> TagOut:
    return TagOut(id=tag.id, name=tag.name, color=tag.color)


# --- routes ---------------------------------------------------------------


@router.get(
    "/watchlist/tags",
    response_model=TagListResponse,
    summary="List this user's watchlist tags + popular suggestions",
)
@limiter.limit("60/minute")
async def list_tags(
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
) -> TagListResponse:
    rows = list(repo.list_for_user(user_id))
    popular = list(repo.popular_for_user(user_id, limit=8))
    return TagListResponse(
        data=[_tag_to_out(r) for r in rows],
        total=len(rows),
        popular=[_tag_to_out(r) for r in popular],
    )


@router.post(
    "/watchlist/tags",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new watchlist tag",
)
@limiter.limit("60/minute")
async def create_tag(
    request: Request,
    response: Response,
    payload: TagCreateRequest,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
) -> TagOut:
    row = repo.create(user_id=user_id, name=payload.name, color=payload.color)
    return _tag_to_out(row)


@router.patch(
    "/watchlist/tags/{tag_id}",
    response_model=TagOut,
    summary="Rename and/or recolor a tag",
)
@limiter.limit("60/minute")
async def update_tag(
    request: Request,
    response: Response,
    tag_id: int,
    payload: TagUpdateRequest,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
) -> TagOut:
    row: WatchlistTag | None = None
    if payload.name is not None:
        row = repo.rename(user_id=user_id, tag_id=tag_id, new_name=payload.name)
    if payload.color is not None:
        row = repo.recolor(user_id=user_id, tag_id=tag_id, new_color=payload.color)
    if row is None:
        # PATCH with empty body returns current state.
        row = repo.get(user_id=user_id, tag_id=tag_id)
        if row is None:
            raise NotFoundError(details={"tag_id": tag_id})
    return _tag_to_out(row)


@router.delete(
    "/watchlist/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tag (CASCADE removes attachments)",
)
@limiter.limit("60/minute")
async def delete_tag(
    request: Request,
    response: Response,
    tag_id: int,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
) -> Response:
    repo.delete(user_id=user_id, tag_id=tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/watchlist/{symbol}/tags/{tag_id}",
    response_model=OkResponse,
    summary="Attach a tag to a watchlist row (idempotent)",
)
@limiter.limit("60/minute")
async def attach_tag(
    request: Request,
    response: Response,
    symbol: str,
    tag_id: int,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
    watchlist_repo: WatchlistRepository = Depends(get_watchlist_repository),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    from app.api.v1.watchlist_routes import validate_symbol_or_raise

    validated = validate_symbol_or_raise(symbol)
    wl_row = watchlist_repo.get(user_id=user_id, symbol=validated)
    if wl_row is None:
        raise NotFoundError(details={"symbol": validated})
    repo.attach(user_id=user_id, watchlist_id=wl_row.id, tag_id=tag_id)
    session.flush()
    return OkResponse()


@router.delete(
    "/watchlist/{symbol}/tags/{tag_id}",
    response_model=OkResponse,
    summary="Detach a tag from a watchlist row (idempotent)",
)
@limiter.limit("60/minute")
async def detach_tag(
    request: Request,
    response: Response,
    symbol: str,
    tag_id: int,
    user_id: int = Depends(current_user_id),
    repo: WatchlistTagRepository = Depends(get_watchlist_tag_repository),
    watchlist_repo: WatchlistRepository = Depends(get_watchlist_repository),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    from app.api.v1.watchlist_routes import validate_symbol_or_raise

    validated = validate_symbol_or_raise(symbol)
    wl_row = watchlist_repo.get(user_id=user_id, symbol=validated)
    if wl_row is None:
        raise NotFoundError(details={"symbol": validated})
    repo.detach(user_id=user_id, watchlist_id=wl_row.id, tag_id=tag_id)
    session.flush()
    return OkResponse()

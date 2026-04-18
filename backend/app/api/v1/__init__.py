"""v1 router composition.

New resource routers register here. Breaking changes → mint `/api/v2/`
(B5) and keep v1 during the migration window.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.auth_routes import router as auth_router
from app.api.v1.data_routes import router as data_router
from app.api.v1.health_routes import router as health_router
from app.api.v1.watchlist_routes import router as watchlist_router


def build_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(auth_router)
    router.include_router(health_router)
    router.include_router(watchlist_router)
    router.include_router(data_router)
    return router

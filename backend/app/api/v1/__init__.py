"""v1 router composition.

New resource routers register here. Breaking changes → mint `/api/v2/`
(B5) and keep v1 during the migration window.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.auth_routes import router as auth_router
from app.api.v1.health_routes import router as health_router


def build_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(auth_router)
    router.include_router(health_router)
    return router

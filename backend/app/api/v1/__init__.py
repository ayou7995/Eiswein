"""v1 router composition.

New resource routers register here. Breaking changes → mint `/api/v2/`
(B5) and keep v1 during the migration window.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin_routes import router as admin_router
from app.api.v1.auth_routes import router as auth_router
from app.api.v1.broker_routes import router as broker_router
from app.api.v1.data_routes import router as data_router
from app.api.v1.health_routes import router as health_router
from app.api.v1.history_routes import router as history_router
from app.api.v1.import_routes import router as import_router
from app.api.v1.indicators_routes import router as indicators_router
from app.api.v1.market_routes import router as market_router
from app.api.v1.positions_routes import router as positions_router
from app.api.v1.settings_routes import router as settings_router
from app.api.v1.ticker_routes import router as ticker_router
from app.api.v1.watchlist_routes import router as watchlist_router


def build_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(auth_router)
    router.include_router(health_router)
    router.include_router(watchlist_router)
    router.include_router(data_router)
    router.include_router(ticker_router)
    router.include_router(market_router)
    router.include_router(positions_router)
    router.include_router(history_router)
    router.include_router(settings_router)
    router.include_router(import_router)
    # Broker routes register unconditionally: individual handlers check
    # ``settings.schwab_enabled`` and 400 with ``schwab_not_configured``
    # when creds are missing. Registering always means the frontend can
    # probe ``GET /broker/schwab/status`` for its UI state without first
    # asking the server "is Schwab configured?".
    router.include_router(broker_router)
    router.include_router(admin_router)
    router.include_router(indicators_router)
    return router

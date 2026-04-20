"""daily_update → signal compose → persist wiring integration test."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import User, Watchlist
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.db.repositories.market_snapshot_repository import MarketSnapshotRepository
from app.db.repositories.ticker_snapshot_repository import TickerSnapshotRepository
from app.ingestion.daily_ingestion import run_daily_update


def _seed_watchlist(
    session_factory: sessionmaker[Session], per_user_symbols: dict[str, list[str]]
) -> None:
    with session_factory() as session:
        for username, symbols in per_user_symbols.items():
            user = User(username=username, password_hash="x")
            session.add(user)
            session.flush()
            for sym in symbols:
                session.add(Watchlist(user_id=user.id, symbol=sym, data_status="pending"))
        session.commit()


@pytest.mark.asyncio
async def test_daily_update_persists_ticker_and_market_snapshots(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    make_price_frame: Callable[..., pd.DataFrame],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    _seed_watchlist(session_factory, {"u1": ["SPY", "AAPL"]})

    frames = {
        "SPY": make_price_frame(days=260, start_price=400.0),
        "AAPL": make_price_frame(days=260, start_price=150.0),
    }
    fake_data_source.config.frames = frames  # type: ignore[attr-defined]

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    assert result.market_open is True
    assert result.snapshots_composed >= 2  # SPY + AAPL
    assert result.snapshots_failed == 0
    assert result.market_posture is not None

    with session_factory() as session:
        ts_repo = TickerSnapshotRepository(session)
        assert ts_repo.get_latest_for_symbol("AAPL") is not None
        assert ts_repo.get_latest_for_symbol("SPY") is not None

        ms_repo = MarketSnapshotRepository(session)
        market = ms_repo.get_latest()
        assert market is not None
        assert market.posture in {"offensive", "normal", "defensive"}
        # Regime counts denormalized for dashboard.
        assert market.regime_green_count + market.regime_red_count + market.regime_yellow_count <= 4

        streak_repo = MarketPostureStreakRepository(session)
        streak = streak_repo.get_latest()
        assert streak is not None
        assert streak.streak_days == 1  # First run of the day.
        assert streak.current_posture == market.posture


@pytest.mark.asyncio
async def test_daily_update_skipped_market_closed_has_empty_snapshots(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: False)
    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )
    assert result.market_open is False
    assert result.snapshots_composed == 0
    assert result.snapshots_failed == 0
    assert result.market_posture is None

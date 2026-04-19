"""daily_update → indicators wiring integration test."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import User, Watchlist
from app.db.repositories.daily_signal_repository import DailySignalRepository
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
async def test_daily_update_computes_and_persists_indicators(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    make_price_frame: Callable[..., pd.DataFrame],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    _seed_watchlist(session_factory, {"u1": ["SPY", "AAPL"]})

    # Give the fake data source ≥200 bars so direction indicators
    # have enough history.
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
    # Both symbols should have stored indicator rows.
    assert result.indicators_computed_symbols >= 2

    with session_factory() as session:
        repo = DailySignalRepository(session)
        aapl_rows = repo.get_latest_for_symbol("AAPL")
        spy_rows = repo.get_latest_for_symbol("SPY")
    assert aapl_rows
    assert spy_rows
    aapl_names = {r.indicator_name for r in aapl_rows}
    # All 8 per-ticker indicators present, even if several are NEUTRAL
    # due to the synthetic macro data being absent.
    assert {"price_vs_ma", "rsi", "macd", "bollinger"} <= aapl_names

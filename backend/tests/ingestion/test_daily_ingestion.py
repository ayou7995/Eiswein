"""daily_update — ONE bulk call, market calendar, graceful degradation."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import User, Watchlist
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
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
                session.add(
                    Watchlist(user_id=user.id, symbol=sym, data_status="pending")
                )
        session.commit()


@pytest.mark.asyncio
async def test_daily_update_issues_exactly_one_bulk_call(
    session_factory: sessionmaker[Session],
    fake_data_source: "object",
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.is_trading_day_et", lambda: True
    )
    _seed_watchlist(
        session_factory,
        {"u1": ["SPY", "QQQ"], "u2": ["SPY", "IWM"]},
    )

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    # distinct_symbols_across_users deduplicates SPY
    assert result.market_open is True
    assert result.symbols_requested == 3
    assert result.symbols_succeeded == 3
    assert result.symbols_failed == 0
    # Exactly one bulk fetch for all 3 distinct symbols
    assert len(fake_data_source.calls) == 1  # type: ignore[attr-defined]
    assert fake_data_source.calls[0][0] == "bulk"  # type: ignore[attr-defined]
    assert sorted(fake_data_source.calls[0][1]) == ["IWM", "QQQ", "SPY"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_daily_update_skips_on_non_trading_day(
    session_factory: sessionmaker[Session],
    fake_data_source: "object",
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.is_trading_day_et", lambda: False
    )
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    assert result.market_open is False
    assert result.symbols_requested == 0
    assert fake_data_source.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_daily_update_isolates_per_symbol_failures(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import FakeDataSource, FakeDataSourceConfig, _make_price_frame

    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.is_trading_day_et", lambda: True
    )

    ds = FakeDataSource(
        FakeDataSourceConfig(
            frames={
                "SPY": _make_price_frame(),
                "QQQ": _make_price_frame(),
            },
            empty_for={"DELIST"},
        )
    )
    _seed_watchlist(session_factory, {"u1": ["SPY", "QQQ", "DELIST"]})

    with session_factory() as session:
        result = await run_daily_update(
            db=session, data_source=ds, settings=settings
        )

    assert result.symbols_requested == 3
    assert result.symbols_succeeded == 2
    assert result.symbols_delisted == 1
    assert result.symbols_failed == 0

    with session_factory() as session:
        prices = DailyPriceRepository(session)
        assert prices.count_for_symbol("SPY") > 0
        assert prices.count_for_symbol("QQQ") > 0
        assert prices.count_for_symbol("DELIST") == 0
        wl = WatchlistRepository(session)
        row = wl.get(user_id=1, symbol="DELIST")
        assert row is not None
        assert row.data_status == "delisted"


@pytest.mark.asyncio
async def test_daily_update_is_idempotent(
    session_factory: sessionmaker[Session],
    fake_data_source: "object",
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.is_trading_day_et", lambda: True
    )
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    with session_factory() as session:
        first = await run_daily_update(
            db=session, data_source=fake_data_source, settings=settings  # type: ignore[arg-type]
        )
        first_rows = DailyPriceRepository(session).count_for_symbol("SPY")

    with session_factory() as session:
        second = await run_daily_update(
            db=session, data_source=fake_data_source, settings=settings  # type: ignore[arg-type]
        )
        second_rows = DailyPriceRepository(session).count_for_symbol("SPY")

    assert first.symbols_succeeded == 1
    assert second.symbols_succeeded == 1
    # UPSERT: same dates → same row count (idempotent).
    assert first_rows == second_rows

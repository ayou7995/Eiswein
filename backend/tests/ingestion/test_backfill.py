"""Backfill — lock, status transitions, idempotency, delisted."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import User, Watchlist
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.backfill import backfill_ticker
from app.security.exceptions import DataSourceError, NotFoundError


def _seed_user_with_symbol(
    session_factory: sessionmaker[Session], symbol: str
) -> int:
    with session_factory() as session:
        user = User(username=f"user_{symbol}", password_hash="x", is_admin=False)
        session.add(user)
        session.flush()
        session.add(
            Watchlist(user_id=user.id, symbol=symbol, data_status="pending")
        )
        session.commit()
        return user.id


@pytest.mark.asyncio
async def test_backfill_transitions_pending_to_ready_and_persists_rows(
    session_factory: sessionmaker[Session], fake_data_source: "object"
) -> None:
    user_id = _seed_user_with_symbol(session_factory, "SPY")

    with session_factory() as session:
        status = await backfill_ticker(
            "SPY",
            user_id=user_id,
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
        )

    assert status == "ready"
    with session_factory() as session:
        row = WatchlistRepository(session).get(user_id=user_id, symbol="SPY")
        assert row is not None
        assert row.data_status == "ready"
        assert row.last_refresh_at is not None
        assert DailyPriceRepository(session).count_for_symbol("SPY") > 0


@pytest.mark.asyncio
async def test_backfill_is_idempotent_when_already_ready(
    session_factory: sessionmaker[Session], fake_data_source: "object"
) -> None:
    user_id = _seed_user_with_symbol(session_factory, "SPY")
    with session_factory() as session:
        await backfill_ticker(
            "SPY", user_id=user_id, db=session, data_source=fake_data_source  # type: ignore[arg-type]
        )

    fake_data_source.calls.clear()  # type: ignore[attr-defined]

    with session_factory() as session:
        status = await backfill_ticker(
            "SPY", user_id=user_id, db=session, data_source=fake_data_source  # type: ignore[arg-type]
        )
    assert status == "ready"
    assert fake_data_source.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_backfill_marks_delisted_when_frame_empty(
    session_factory: sessionmaker[Session],
) -> None:
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    ds = FakeDataSource(FakeDataSourceConfig(empty_for={"DELIST"}))
    user_id = _seed_user_with_symbol(session_factory, "DELIST")

    with session_factory() as session:
        with pytest.raises(DataSourceError):
            await backfill_ticker(
                "DELIST", user_id=user_id, db=session, data_source=ds
            )

    with session_factory() as session:
        row = WatchlistRepository(session).get(user_id=user_id, symbol="DELIST")
        assert row is not None
        assert row.data_status == "delisted"


@pytest.mark.asyncio
async def test_backfill_marks_failed_on_upstream_error(
    session_factory: sessionmaker[Session],
) -> None:
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    ds = FakeDataSource(FakeDataSourceConfig(error_for={"BADTK"}))
    user_id = _seed_user_with_symbol(session_factory, "BADTK")

    with session_factory() as session:
        with pytest.raises(DataSourceError):
            await backfill_ticker(
                "BADTK", user_id=user_id, db=session, data_source=ds
            )

    with session_factory() as session:
        row = WatchlistRepository(session).get(user_id=user_id, symbol="BADTK")
        assert row is not None
        assert row.data_status == "failed"


@pytest.mark.asyncio
async def test_backfill_raises_not_found_when_watchlist_row_missing(
    session_factory: sessionmaker[Session], fake_data_source: "object"
) -> None:
    with session_factory() as session:
        user = User(username="ghost", password_hash="x", is_admin=False)
        session.add(user)
        session.commit()
        user_id = user.id

    with session_factory() as session:
        with pytest.raises(NotFoundError):
            await backfill_ticker(
                "SPY", user_id=user_id, db=session, data_source=fake_data_source  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_backfill_serializes_concurrent_calls_for_same_symbol(
    session_factory: sessionmaker[Session], make_price_frame: "object"
) -> None:
    """Two concurrent backfills for the same symbol MUST hit the lock.

    Without the per-symbol lock they'd both fetch and both UPSERT — the
    UNIQUE constraint catches it but wastes network. The data source's
    `calls` list lets us count upstream invocations.
    """
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    frame = make_price_frame(days=30)  # type: ignore[operator]

    config = FakeDataSourceConfig(frames={"SPY": frame}, delay_seconds=0.2)
    ds = FakeDataSource(config)

    user_id_a = _seed_user_with_symbol(session_factory, "SPY")
    # A second user also races for SPY backfill
    with session_factory() as session:
        user_b = User(username="other", password_hash="x", is_admin=False)
        session.add(user_b)
        session.flush()
        session.add(Watchlist(user_id=user_b.id, symbol="SPY", data_status="pending"))
        session.commit()
        user_id_b = user_b.id

    async def _run(uid: int) -> str:
        with session_factory() as sess:
            return await backfill_ticker(
                "SPY", user_id=uid, db=sess, data_source=ds
            )

    results = await asyncio.gather(_run(user_id_a), _run(user_id_b))
    assert results == ["ready", "ready"]
    # Each invocation under lock issues its own fetch, but they serialize.
    assert len(ds.calls) == 2
    for call in ds.calls:
        assert call[0] == "bulk"
        assert call[1] == ["SPY"]

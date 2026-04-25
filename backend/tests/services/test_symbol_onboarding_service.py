"""SymbolOnboardingService — cold-start, gap-fill, cancellation, re-add."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import (
    BackfillJob,
    DailyPrice,
    MarketSnapshot,
    TickerSnapshot,
    User,
    Watchlist,
)
from app.db.repositories.backfill_job_repository import BackfillJobRepository
from app.services.symbol_onboarding_service import (
    OnboardingAlreadyRunningError,
    SymbolOnboardingService,
)
from tests.conftest import FakeDataSource, FakeDataSourceConfig

# --- helpers --------------------------------------------------------------


def _seed_user_with_pending_watchlist(
    session_factory: sessionmaker[Session],
    *,
    username: str = "tester",
    symbol: str = "NVDA",
) -> int:
    with session_factory() as session:
        user = User(username=username, password_hash="x")
        session.add(user)
        session.flush()
        session.add(
            Watchlist(
                user_id=user.id,
                symbol=symbol,
                data_status="pending",
            )
        )
        session.commit()
        return int(user.id)


def _seed_market_snapshots(
    session_factory: sessionmaker[Session],
    *,
    start: date,
    days: int,
) -> None:
    with session_factory() as session:
        for i in range(days):
            session.add(
                MarketSnapshot(
                    date=start + timedelta(days=i),
                    posture="normal",
                    regime_green_count=0,
                    regime_red_count=0,
                    regime_yellow_count=4,
                    indicator_version="v1.0.0",
                    computed_at=datetime.now(UTC),
                )
            )
        session.commit()


def _seed_daily_prices(
    session_factory: sessionmaker[Session],
    *,
    symbol: str,
    start: date,
    days: int,
    start_price: float = 100.0,
) -> None:
    with session_factory() as session:
        for i in range(days):
            d = start + timedelta(days=i)
            close = start_price + 0.5 * ((i % 20) - 10)
            session.add(
                DailyPrice(
                    symbol=symbol,
                    date=d,
                    open=Decimal(str(close - 0.5)),
                    high=Decimal(str(close + 1.0)),
                    low=Decimal(str(close - 1.0)),
                    close=Decimal(str(close)),
                    volume=1_000_000 + i * 1_000,
                )
            )
        session.commit()


def _wait_for_state(
    session_factory: sessionmaker[Session],
    job_id: int,
    terminal: set[str],
    timeout: float = 30.0,
) -> BackfillJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with session_factory() as session:
            row = session.execute(select(BackfillJob).where(BackfillJob.id == job_id)).scalar_one()
            if row.state in terminal:
                return row
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {terminal}")


# --- tests ----------------------------------------------------------------


def test_happy_path_fetches_prices_and_fills_snapshots(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="NVDA")
    # A few market_snapshot dates — the gap-fill should produce
    # ticker_snapshot rows for each.
    today = date(2026, 4, 22)
    _seed_market_snapshots(session_factory, start=today - timedelta(days=4), days=5)
    # Seed SPY history so build_context has the SPX proxy frame.
    _seed_daily_prices(
        session_factory,
        symbol="SPY",
        start=today - timedelta(days=800),
        days=800,
        start_price=400.0,
    )

    ds = FakeDataSource(FakeDataSourceConfig())
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=True,
    )

    job = service.start(symbol="NVDA", user_id=user_id)
    finished = _wait_for_state(session_factory, job.id, {"completed", "failed"})
    assert finished.state == "completed", f"runner failed: {finished.error!r}"
    assert finished.kind == "onboarding"
    assert finished.symbol == "NVDA"

    with session_factory() as session:
        watchlist = session.execute(
            select(Watchlist).where(Watchlist.symbol == "NVDA")
        ).scalar_one()
        assert watchlist.data_status == "ready"

        prices = (
            session.execute(select(DailyPrice).where(DailyPrice.symbol == "NVDA")).scalars().all()
        )
        assert len(prices) > 0


def test_delisted_symbol_sets_failed_state(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="ZZZZ")
    ds = FakeDataSource(FakeDataSourceConfig(empty_for={"ZZZZ"}))
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=True,
    )
    job = service.start(symbol="ZZZZ", user_id=user_id)
    finished = _wait_for_state(session_factory, job.id, {"completed", "failed"})
    assert finished.state == "failed"
    assert finished.error is not None
    assert "ZZZZ" in finished.error


def test_cancellation_between_dates_stops_early(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel flag set after phase-1 → phase-2 exits without processing."""
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="NVDA")
    today = date(2026, 4, 22)
    _seed_market_snapshots(session_factory, start=today - timedelta(days=10), days=11)
    _seed_daily_prices(
        session_factory,
        symbol="SPY",
        start=today - timedelta(days=800),
        days=800,
        start_price=400.0,
    )

    ds = FakeDataSource(FakeDataSourceConfig())
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=True,
    )

    # Before the runner fires, pre-seed the cancel flag on the row that
    # service.start is about to create. We do this by patching
    # BackfillJobRepository.create to flip cancel_requested immediately.
    original_create = BackfillJobRepository.create

    def _create_and_cancel(self, **kwargs):  # type: ignore[no-untyped-def]
        row = original_create(self, **kwargs)
        row.cancel_requested = True
        self._session.flush()
        return row

    monkeypatch.setattr(BackfillJobRepository, "create", _create_and_cancel)

    job = service.start(symbol="NVDA", user_id=user_id)
    finished = _wait_for_state(session_factory, job.id, {"completed", "cancelled", "failed"})
    assert finished.state == "cancelled"


def test_onboarding_rejected_when_revalidation_active(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    """Revalidation rewrites every symbol so a new onboarding must wait."""
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="NVDA")
    with session_factory() as session:
        session.add(
            BackfillJob(
                kind="revalidation",
                symbol=None,
                from_date=date(2026, 4, 1),
                to_date=date(2026, 4, 2),
                state="running",
                force=True,
                created_by_user_id=user_id,
            )
        )
        session.commit()

    ds = FakeDataSource(FakeDataSourceConfig())
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=True,
    )
    with pytest.raises(OnboardingAlreadyRunningError):
        service.start(symbol="NVDA", user_id=user_id)


def test_concurrent_onboardings_both_succeed(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two onboardings in quick succession both create rows; the second
    is not rejected even though the first's job row is still ``pending``.

    Patches ``Thread.start`` to a no-op so neither runner touches the
    in-memory DB on a worker thread (which would race the StaticPool
    teardown). We're only asserting on the ``start`` method's queue-
    instead-of-409 behaviour, not the runner itself.
    """
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="NVDA")
    with session_factory() as session:
        session.add(Watchlist(user_id=user_id, symbol="AMD", data_status="pending"))
        session.commit()

    import threading as _threading

    monkeypatch.setattr(_threading.Thread, "start", lambda self: None)

    ds = FakeDataSource(FakeDataSourceConfig())
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=False,
    )

    first = service.start(symbol="NVDA", user_id=user_id)
    second = service.start(symbol="AMD", user_id=user_id)

    assert first.id != second.id
    assert first.kind == "onboarding"
    assert second.kind == "onboarding"
    assert first.symbol == "NVDA"
    assert second.symbol == "AMD"

    with session_factory() as session:
        rows = (
            session.execute(select(BackfillJob).where(BackfillJob.kind == "onboarding"))
            .scalars()
            .all()
        )
        assert {r.symbol for r in rows} == {"NVDA", "AMD"}
        assert all(r.state == "pending" for r in rows)


def test_reonboarding_reuses_existing_snapshot_rows(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    """Re-adding a symbol reuses already-written ticker_snapshot rows.

    First onboarding fills history, we then delete the watchlist row
    but the ticker_snapshots remain. A second add should succeed
    quickly (snapshots already present → phase 2 skips) and leave the
    job ``completed``.
    """
    user_id = _seed_user_with_pending_watchlist(session_factory, symbol="NVDA")
    today = date(2026, 4, 22)
    _seed_market_snapshots(session_factory, start=today - timedelta(days=3), days=4)
    _seed_daily_prices(
        session_factory,
        symbol="SPY",
        start=today - timedelta(days=800),
        days=800,
        start_price=400.0,
    )

    ds = FakeDataSource(FakeDataSourceConfig())
    service = SymbolOnboardingService(
        session_factory=session_factory,
        settings=settings,
        data_source=ds,
        run_inline=True,
    )
    first = service.start(symbol="NVDA", user_id=user_id)
    _wait_for_state(session_factory, first.id, {"completed", "failed"})

    with session_factory() as session:
        initial_snapshots = (
            session.execute(select(TickerSnapshot).where(TickerSnapshot.symbol == "NVDA"))
            .scalars()
            .all()
        )
        assert len(initial_snapshots) > 0
        # Simulate user deleting the watchlist row; snapshots remain.
        watchlist = session.execute(
            select(Watchlist).where(Watchlist.symbol == "NVDA")
        ).scalar_one()
        session.delete(watchlist)
        session.commit()
    with session_factory() as session:
        session.add(Watchlist(user_id=user_id, symbol="NVDA", data_status="pending"))
        session.commit()

    second = service.start(symbol="NVDA", user_id=user_id)
    finished = _wait_for_state(session_factory, second.id, {"completed", "failed"})
    assert finished.state == "completed"

    with session_factory() as session:
        final_snapshots = (
            session.execute(select(TickerSnapshot).where(TickerSnapshot.symbol == "NVDA"))
            .scalars()
            .all()
        )
        # No duplicate rows created — gap-fill short-circuits on existing dates.
        assert len(final_snapshots) == len(initial_snapshots)

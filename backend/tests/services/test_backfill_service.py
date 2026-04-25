"""BackfillService — revalidate_all_snapshots runner + orphan cleanup.

Post Phase-1 UX overhaul the service's only orchestration surface is
:meth:`BackfillService.revalidate_all_snapshots`. There is no plan()
/ create_and_start() anymore; tests covering those have been dropped.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from app.services.backfill_service import (
    BackfillAlreadyRunningError,
    BackfillService,
    mark_orphaned_backfills_failed,
)

# --- Shared helpers -------------------------------------------------------


def _seed_user_and_watchlist(
    session_factory: sessionmaker[Session],
    *,
    username: str = "tester",
    symbols: tuple[str, ...] = ("SPY", "AAPL"),
) -> int:
    with session_factory() as session:
        user = User(username=username, password_hash="x")
        session.add(user)
        session.flush()
        for sym in symbols:
            session.add(
                Watchlist(
                    user_id=user.id,
                    symbol=sym,
                    data_status="ready",
                )
            )
        session.commit()
        return int(user.id)


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


def _patch_trading_day_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``get_trading_days(start, end)`` return every calendar day."""

    def _fake_get_trading_days(start: date, end: date) -> list[date]:
        if end < start:
            return []
        days: list[date] = []
        d = start
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
        return days

    monkeypatch.setattr(
        "app.services.backfill_service.get_trading_days",
        _fake_get_trading_days,
    )


def _patch_today_et(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(
        "app.services.backfill_service.today_et",
        lambda: today,
    )


def _seed_market_snapshots(
    session_factory: sessionmaker[Session],
    *,
    start: date,
    days: int,
) -> None:
    """Seed ``days`` consecutive market_snapshot rows used as the
    revalidation range anchor (oldest row becomes from_date)."""
    with session_factory() as session:
        for i in range(days):
            session.add(
                MarketSnapshot(
                    date=start + timedelta(days=i),
                    posture="normal",
                    regime_green_count=0,
                    regime_red_count=0,
                    regime_yellow_count=4,
                    indicator_version="vOLD",
                    computed_at=datetime.now(UTC),
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
    msg = f"job {job_id} did not reach {terminal} within {timeout}s"
    raise AssertionError(msg)


# --- revalidate_all_snapshots ---------------------------------------------


def test_revalidate_happy_path_writes_snapshots_and_rebuilds_streaks(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    today = date(2026, 4, 22)
    _patch_today_et(monkeypatch, today)
    _patch_trading_day_identity(monkeypatch)

    user_id = _seed_user_and_watchlist(session_factory, symbols=("SPY", "AAPL"))
    # Seed market snapshots to set the revalidation range.
    _seed_market_snapshots(session_factory, start=date(2026, 4, 10), days=5)

    history_start = date(2024, 4, 1)
    history_days = (today - history_start).days + 7
    _seed_daily_prices(
        session_factory,
        symbol="SPY",
        start=history_start,
        days=history_days,
        start_price=400.0,
    )
    _seed_daily_prices(
        session_factory,
        symbol="AAPL",
        start=history_start,
        days=history_days,
        start_price=150.0,
    )

    service = BackfillService(
        session_factory=session_factory,
        settings=settings,
        run_inline=True,
    )
    job = service.revalidate_all_snapshots(user_id=user_id)

    finished = _wait_for_state(session_factory, job.id, {"completed", "failed"})
    assert finished.state == "completed", f"runner failed: {finished.error!r}"
    assert finished.force is True
    assert finished.kind == "revalidation"

    with session_factory() as session:
        ticker_rows = (
            session.execute(
                select(TickerSnapshot)
                .where(TickerSnapshot.date >= date(2026, 4, 10))
                .where(TickerSnapshot.date <= today)
            )
            .scalars()
            .all()
        )
        assert ticker_rows, "expected at least one ticker snapshot written"


def test_revalidate_rejects_when_active_job_exists(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_today_et(monkeypatch, date(2026, 4, 22))
    user_id = _seed_user_and_watchlist(session_factory)

    with session_factory() as session:
        session.add(
            BackfillJob(
                kind="revalidation",
                symbol=None,
                from_date=date(2026, 4, 1),
                to_date=date(2026, 4, 5),
                state="pending",
                force=True,
                created_by_user_id=user_id,
            )
        )
        session.commit()

    service = BackfillService(session_factory=session_factory, settings=settings)
    with pytest.raises(BackfillAlreadyRunningError):
        service.revalidate_all_snapshots(user_id=user_id)


def test_revalidate_cancellation_stops_between_days(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 4, 22)
    _patch_today_et(monkeypatch, today)
    _patch_trading_day_identity(monkeypatch)

    user_id = _seed_user_and_watchlist(session_factory, symbols=("SPY",))
    _seed_market_snapshots(session_factory, start=date(2026, 4, 10), days=11)
    _seed_daily_prices(
        session_factory,
        symbol="SPY",
        start=date(2024, 4, 1),
        days=800,
        start_price=400.0,
    )

    barrier = threading.Event()
    original_incr = BackfillJobRepository.increment_progress

    def _paced_increment(
        self: BackfillJobRepository,
        job_id: int,
        *,
        processed: int = 0,
        skipped: int = 0,
        failed: int = 0,
    ) -> BackfillJob:
        row = original_incr(self, job_id, processed=processed, skipped=skipped, failed=failed)
        if row.processed_days == 2 and not barrier.is_set():
            with session_factory() as gate_session:
                BackfillJobRepository(gate_session).request_cancel(job_id)
                gate_session.commit()
            barrier.set()
        return row

    monkeypatch.setattr(BackfillJobRepository, "increment_progress", _paced_increment)

    service = BackfillService(
        session_factory=session_factory,
        settings=settings,
        run_inline=True,
    )
    job = service.revalidate_all_snapshots(user_id=user_id)

    finished = _wait_for_state(session_factory, job.id, {"cancelled", "failed", "completed"})
    assert finished.state == "cancelled"


def test_revalidate_empty_history_no_op_completes(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No market_snapshot rows exist → from_date=to_date=today, single-day run."""
    today = date(2026, 4, 22)
    _patch_today_et(monkeypatch, today)
    _patch_trading_day_identity(monkeypatch)
    user_id = _seed_user_and_watchlist(session_factory, symbols=("SPY",))

    service = BackfillService(
        session_factory=session_factory,
        settings=settings,
        run_inline=True,
    )
    job = service.revalidate_all_snapshots(user_id=user_id)
    finished = _wait_for_state(session_factory, job.id, {"completed", "failed"})
    # from==to==today: one day to process. With no seeded history the
    # indicators will fail softly and the day is counted as failed;
    # but the job still terminates in ``completed``.
    assert finished.state == "completed"


# --- Orphan cleanup ------------------------------------------------------


def test_mark_orphaned_backfills_failed_flips_running_row(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add_all(
            [
                BackfillJob(
                    kind="revalidation",
                    symbol=None,
                    from_date=date(2026, 4, 1),
                    to_date=date(2026, 4, 1),
                    state="running",
                    force=True,
                    created_by_user_id=1,
                ),
                BackfillJob(
                    kind="onboarding",
                    symbol="AAPL",
                    from_date=date(2026, 4, 2),
                    to_date=date(2026, 4, 2),
                    state="pending",
                    force=False,
                    created_by_user_id=1,
                ),
                BackfillJob(
                    kind="revalidation",
                    symbol=None,
                    from_date=date(2026, 4, 3),
                    to_date=date(2026, 4, 3),
                    state="completed",
                    force=True,
                    created_by_user_id=1,
                ),
            ]
        )
        session.commit()

    with session_factory() as session:
        count = mark_orphaned_backfills_failed(session=session)
        session.commit()
    assert count == 2

    with session_factory() as session:
        rows = (
            session.execute(select(BackfillJob).order_by(BackfillJob.from_date.asc()))
            .scalars()
            .all()
        )
        assert rows[0].state == "failed"
        assert rows[0].error == "orphaned_by_restart"
        assert rows[1].state == "failed"
        assert rows[2].state == "completed"

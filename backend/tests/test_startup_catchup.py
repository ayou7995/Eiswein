"""Lifespan startup catch-up — fires daily_update once on boot.

Handles the laptop-sleep scenario: APScheduler's 06:30 ET cron fires
into the void when the host is asleep, but a single restart later we
catch up the gap. Tests gate on whether the scheduler runs, mirroring
production behaviour.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.daily_ingestion import DailyUpdateResult
from app.main import create_app
from tests.conftest import FakeDataSource


def _stub_result() -> DailyUpdateResult:
    return DailyUpdateResult(
        market_open=True,
        session_date=date(2026, 5, 27),
        symbols_requested=1,
        symbols_succeeded=1,
        symbols_failed=0,
        symbols_delisted=0,
        price_rows_upserted=0,
        macro_rows_upserted=0,
        macro_series_failed=0,
        indicators_computed_symbols=1,
        indicators_failed_symbols=0,
        snapshots_composed=1,
        snapshots_failed=0,
        market_posture=None,
    )


def _enable_scheduler_with_stub(application: FastAPI) -> None:
    """Bypass the real APScheduler start path while still telling
    lifespan that the scheduler is "running" — that gate is what
    enables the catch-up task in production."""
    application.state.scheduler_disabled = False
    application.state.scheduler_handle = MagicMock(name="scheduler_handle")


def test_startup_catchup_runs_when_scheduler_enabled(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
) -> None:
    """Booting with the scheduler running schedules and awaits one
    daily_update — mirrors what happens when the user `make start`s
    after the laptop has been asleep for a few hours."""
    mock_run = AsyncMock(return_value=_stub_result())
    with patch("app.main.run_daily_update", mock_run):
        app = create_app(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.data_source = fake_data_source
        _enable_scheduler_with_stub(app)
        # Inline onboarding / backfill so the TestClient ctx mgr exit
        # doesn't block on a worker thread.
        app.state.onboarding_run_inline = True
        app.state.backfill_run_inline = True
        with TestClient(app):
            # ``TestClient(app).__exit__`` awaits any pending tasks
            # the lifespan created, including the catch-up.
            pass
    assert mock_run.await_count == 1


def test_startup_catchup_skipped_when_scheduler_disabled(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
) -> None:
    """The standard test fixture sets ``scheduler_disabled = True``.
    No scheduler → no catch-up; otherwise every TestClient lifespan
    cycle in the suite would re-hit yfinance / FRED."""
    mock_run = AsyncMock(return_value=_stub_result())
    with patch("app.main.run_daily_update", mock_run):
        app = create_app(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.data_source = fake_data_source
        # Default — scheduler off.
        app.state.scheduler_disabled = True
        app.state.onboarding_run_inline = True
        app.state.backfill_run_inline = True
        with TestClient(app):
            pass
    mock_run.assert_not_awaited()


def test_startup_catchup_suppressed_via_dedicated_flag(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
) -> None:
    """A scheduler-enabled test can still skip catch-up by setting
    ``startup_catchup_disabled = True`` — used by jobs/scheduler
    integration tests that exercise APScheduler but don't want a
    spurious daily_update flooding the assertions."""
    mock_run = AsyncMock(return_value=_stub_result())
    with patch("app.main.run_daily_update", mock_run):
        app = create_app(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.data_source = fake_data_source
        _enable_scheduler_with_stub(app)
        app.state.startup_catchup_disabled = True
        app.state.onboarding_run_inline = True
        app.state.backfill_run_inline = True
        with TestClient(app):
            pass
    mock_run.assert_not_awaited()


def test_startup_catchup_survives_failure(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
) -> None:
    """daily_update blowing up at startup must not abort lifespan —
    a flaky yfinance shouldn't keep the API offline."""
    boom = AsyncMock(side_effect=RuntimeError("upstream dead"))
    with patch("app.main.run_daily_update", boom):
        app = create_app(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.data_source = fake_data_source
        _enable_scheduler_with_stub(app)
        app.state.onboarding_run_inline = True
        app.state.backfill_run_inline = True
        # No exception escapes — the TestClient lifespan completes.
        with TestClient(app) as tc:
            # And the API still serves.
            assert tc.get("/api/v1/health").status_code == 200
    assert boom.await_count == 1


@pytest.mark.parametrize("flag_value", [None, True, False])
def test_startup_catchup_task_attached_to_app_state(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    fake_data_source: FakeDataSource,
    flag_value: bool | None,
) -> None:
    """Sanity: ``app.state.startup_catchup_task`` is always set
    (None when skipped, a Task otherwise) so tests / observability
    have a single place to inspect."""
    mock_run = AsyncMock(return_value=_stub_result())
    with patch("app.main.run_daily_update", mock_run):
        app = create_app(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.data_source = fake_data_source
        if flag_value is True or flag_value is None:
            _enable_scheduler_with_stub(app)
        else:
            app.state.scheduler_disabled = True
        app.state.onboarding_run_inline = True
        app.state.backfill_run_inline = True
        with TestClient(app):
            # Task should be set on state regardless of branch taken.
            assert hasattr(app.state, "startup_catchup_task")

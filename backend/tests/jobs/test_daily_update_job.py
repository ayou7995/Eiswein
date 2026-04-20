"""Tests for :mod:`app.jobs.daily_update`."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.daily_ingestion import DailyUpdateResult
from app.jobs import daily_update as daily_update_job
from app.signals.types import MarketPosture


def _ok_result() -> DailyUpdateResult:
    return DailyUpdateResult(
        market_open=True,
        session_date=date(2026, 4, 17),
        symbols_requested=3,
        symbols_succeeded=3,
        symbols_failed=0,
        symbols_delisted=0,
        price_rows_upserted=30,
        macro_rows_upserted=5,
        macro_series_failed=0,
        indicators_computed_symbols=3,
        indicators_failed_symbols=0,
        snapshots_composed=3,
        snapshots_failed=0,
        market_posture=MarketPosture.NORMAL,
    )


def _closed_result() -> DailyUpdateResult:
    return DailyUpdateResult(
        market_open=False,
        session_date=date(2026, 4, 18),
        symbols_requested=0,
        symbols_succeeded=0,
        symbols_failed=0,
        symbols_delisted=0,
        price_rows_upserted=0,
        macro_rows_upserted=0,
        macro_series_failed=0,
        indicators_computed_symbols=0,
        indicators_failed_symbols=0,
        snapshots_composed=0,
        snapshots_failed=0,
        market_posture=None,
    )


@pytest.mark.asyncio
async def test_market_closed_skips_email_and_metadata(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fake_data_source: MagicMock,
) -> None:
    with (
        patch.object(
            daily_update_job,
            "run_daily_update",
            new=AsyncMock(return_value=_closed_result()),
        ),
        patch.object(daily_update_job, "send_daily_summary") as email_mock,
        patch.object(daily_update_job, "_record_last_update") as record_mock,
    ):
        result = await daily_update_job.run(
            session_factory=session_factory,
            data_source=fake_data_source,
            settings=settings,
        )

    assert result is not None
    assert result.market_open is False
    email_mock.assert_not_called()
    record_mock.assert_not_called()


@pytest.mark.asyncio
async def test_market_open_dispatches_email_and_records(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fake_data_source: MagicMock,
) -> None:
    ok_result = _ok_result()
    with (
        patch.object(
            daily_update_job,
            "run_daily_update",
            new=AsyncMock(return_value=ok_result),
        ),
        patch.object(daily_update_job, "send_daily_summary") as email_mock,
        patch.object(daily_update_job, "_record_last_update") as record_mock,
    ):
        result = await daily_update_job.run(
            session_factory=session_factory,
            data_source=fake_data_source,
            settings=settings,
        )

    assert result is ok_result
    email_mock.assert_called_once()
    kwargs = email_mock.call_args.kwargs
    assert kwargs["result"] is ok_result
    assert kwargs["settings"] is settings
    # Snapshot list is pulled from the DB (empty in this test because
    # no rows were written) but must still be a list.
    assert isinstance(kwargs["snapshots"], list)

    record_mock.assert_called_once()


@pytest.mark.asyncio
async def test_run_daily_update_exception_returns_none_without_raising(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fake_data_source: MagicMock,
) -> None:
    with patch.object(
        daily_update_job,
        "run_daily_update",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await daily_update_job.run(
            session_factory=session_factory,
            data_source=fake_data_source,
            settings=settings,
        )
    assert result is None


@pytest.mark.asyncio
async def test_email_failure_does_not_block_metadata(
    settings: Settings,
    session_factory: sessionmaker[Session],
    fake_data_source: MagicMock,
) -> None:
    ok_result = _ok_result()
    with (
        patch.object(
            daily_update_job,
            "run_daily_update",
            new=AsyncMock(return_value=ok_result),
        ),
        patch.object(
            daily_update_job,
            "send_daily_summary",
            side_effect=RuntimeError("email down"),
        ),
        patch.object(daily_update_job, "_record_last_update") as record_mock,
    ):
        result = await daily_update_job.run(
            session_factory=session_factory,
            data_source=fake_data_source,
            settings=settings,
        )

    assert result is ok_result
    record_mock.assert_called_once()

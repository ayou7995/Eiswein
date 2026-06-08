"""Tests for the intraday VIX/VIX3M refresh job (Phase 6)."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.db.models import MacroIndicator
from app.jobs.intraday_vix_refresh import _is_market_hours, run

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

_NY = ZoneInfo("America/New_York")


# --- _is_market_hours -------------------------------------------------------


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        # Weekday at 09:30:00 ET → open
        (datetime(2026, 6, 5, 9, 30, tzinfo=_NY), True),
        # Weekday at 12:00:00 ET → open
        (datetime(2026, 6, 5, 12, 0, tzinfo=_NY), True),
        # Weekday at 16:30:00 ET → still capture the closing bar
        (datetime(2026, 6, 5, 16, 30, tzinfo=_NY), True),
        # Weekday at 16:31:00 ET → past close window
        (datetime(2026, 6, 5, 16, 31, tzinfo=_NY), False),
        # Weekday at 09:29:00 ET → pre-open
        (datetime(2026, 6, 5, 9, 29, tzinfo=_NY), False),
        # Saturday → no
        (datetime(2026, 6, 6, 12, 0, tzinfo=_NY), False),
        # Sunday → no
        (datetime(2026, 6, 7, 12, 0, tzinfo=_NY), False),
    ],
)
def test_is_market_hours(dt: datetime, expected: bool) -> None:
    assert _is_market_hours(dt) is expected


def test_is_market_hours_handles_utc_input() -> None:
    """Caller may pass UTC clocks — must convert to ET internally."""
    # 2026-06-05 13:00 UTC = 09:00 ET (before open) on a weekday.
    utc_pre_open = datetime(2026, 6, 5, 13, 0, tzinfo=ZoneInfo("UTC"))
    assert _is_market_hours(utc_pre_open) is False
    # 2026-06-05 14:00 UTC = 10:00 ET (open) on a weekday.
    utc_open = datetime(2026, 6, 5, 14, 0, tzinfo=ZoneInfo("UTC"))
    assert _is_market_hours(utc_open) is True


# --- run() integration ------------------------------------------------------


@pytest.mark.asyncio
async def test_run_skips_off_hours(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the job fires outside market hours (e.g. weekend cron),
    it returns without hitting yfinance or the DB."""

    class _FakeSource:
        fetch_today_running = AsyncMock(return_value={})

    fake_source = _FakeSource()
    # Force "now" to a Saturday so the gate is False regardless of when
    # the test actually runs.
    monkeypatch.setattr(
        "app.jobs.intraday_vix_refresh.datetime",
        _FixedClock(datetime(2026, 6, 6, 12, 0, tzinfo=_NY)),
    )
    await run(session_factory=session_factory, data_source=fake_source)  # type: ignore[arg-type]
    fake_source.fetch_today_running.assert_not_called()


def _running_bar(close: float, when: datetime) -> pd.DataFrame:
    """Stand-in for ``fetch_today_running``'s per-symbol frame: a single
    OHLCV row indexed by ``when``."""
    return pd.DataFrame(
        {
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [0],
        },
        index=pd.DatetimeIndex([pd.Timestamp(when)]),
    )


@pytest.mark.asyncio
async def test_run_writes_upsert_during_market_hours(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During market hours, the job fetches yfinance + UPSERTs both
    VIXCLS and VXVCLS rows."""
    bar_when = datetime(2026, 6, 5, 11, 0, tzinfo=_NY)

    class _FakeSource:
        fetch_today_running = AsyncMock(
            return_value={
                "^VIX": _running_bar(18.42, bar_when),
                "^VIX3M": _running_bar(19.30, bar_when),
            }
        )

    fake_source = _FakeSource()
    # Mid-day Wednesday — guaranteed market hours.
    monkeypatch.setattr(
        "app.jobs.intraday_vix_refresh.datetime",
        _FixedClock(datetime(2026, 6, 3, 12, 0, tzinfo=_NY)),
    )

    await run(session_factory=session_factory, data_source=fake_source)  # type: ignore[arg-type]

    with session_factory() as session:
        rows = (
            session.query(MacroIndicator)
            .filter(MacroIndicator.date == bar_when.date())
            .order_by(MacroIndicator.series_id)
            .all()
        )
    series = {r.series_id: r.value for r in rows}
    assert series["VIXCLS"] == Decimal("18.42")
    assert series["VXVCLS"] == Decimal("19.30")


@pytest.mark.asyncio
async def test_run_handles_missing_bar_gracefully(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When yfinance returns an empty frame for ^VIX3M (e.g. index data
    delisted / network blip), the VIX row still gets written and the
    job doesn't raise."""
    bar_when = datetime(2026, 6, 5, 11, 0, tzinfo=_NY)

    class _FakeSource:
        fetch_today_running = AsyncMock(
            return_value={
                "^VIX": _running_bar(18.42, bar_when),
                "^VIX3M": pd.DataFrame(),
            }
        )

    fake_source = _FakeSource()
    monkeypatch.setattr(
        "app.jobs.intraday_vix_refresh.datetime",
        _FixedClock(datetime(2026, 6, 3, 12, 0, tzinfo=_NY)),
    )
    await run(session_factory=session_factory, data_source=fake_source)  # type: ignore[arg-type]

    with session_factory() as session:
        rows = (
            session.query(MacroIndicator)
            .filter(MacroIndicator.date == bar_when.date())
            .all()
        )
    series = {r.series_id: r.value for r in rows}
    assert "VIXCLS" in series
    assert "VXVCLS" not in series


# --- helpers ---------------------------------------------------------------


class _FixedClock:
    """Minimal stand-in for ``datetime`` so ``datetime.now(tz)`` returns
    a deterministic value. Only the calls the job module uses are
    proxied — everything else falls through to the real class."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self, tz: ZoneInfo | None = None) -> datetime:
        if tz is None:
            return self._now.replace(tzinfo=None)
        return self._now.astimezone(tz)

    def __getattr__(self, name: str) -> object:
        return getattr(datetime, name)


@pytest.fixture
def time_imports_kept() -> None:
    # Pure import smoke — `time` and `ZoneInfo` must remain importable
    # so the schema doesn't drift.
    assert time is not None
    assert ZoneInfo is not None

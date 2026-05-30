"""Weekly Gemini industry sync — budget guard + idempotent upsert."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.calendar_event_repository import CalendarEventRow
from app.db.repositories.system_metadata_repository import SystemMetadataRepository
from app.ingestion import industry_gemini_sync as mod
from app.ingestion.industry_gemini_sync import (
    KEY_GEMINI_REQUESTS_BUDGET,
    KEY_LAST_INDUSTRY_SYNC_AT,
    run_industry_gemini_sync,
)


def _stub_fetch(rows: list[CalendarEventRow]) -> Any:
    async def _impl(*, api_key: str, as_of: date) -> list[CalendarEventRow]:
        return rows

    return _impl


def _row(*, title: str, when: date) -> CalendarEventRow:
    return CalendarEventRow(
        event_date=when,
        event_time=None,
        type="industry",
        ticker_symbol=None,
        title=title,
        payload_json={"confidence": "confirmed"},
        source="gemini",
    )


# --- no-key short-circuit ------------------------------------------------


@pytest.mark.asyncio
async def test_run_short_circuits_when_api_key_missing(db_session: Session) -> None:
    result = await run_industry_gemini_sync(db_session, api_key="")
    assert result.skipped_reason == "no_api_key"
    assert result.events_returned == 0
    assert result.rows_upserted == 0


# --- happy path ----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_upserts_rows_and_records_last_sync_at(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_rows = [
        _row(title="Computex 2027", when=date(2027, 5, 25)),
        _row(title="WWDC 2026 Keynote", when=date(2026, 6, 8)),
    ]
    monkeypatch.setattr(mod, "fetch_upcoming_industry_events", _stub_fetch(fixture_rows))

    result = await run_industry_gemini_sync(db_session, api_key="fake-key", as_of=date(2026, 5, 31))
    assert result.skipped_reason is None
    assert result.events_returned == 2
    assert result.rows_upserted == 2

    metadata = SystemMetadataRepository(db_session)
    assert metadata.get_datetime(KEY_LAST_INDUSTRY_SYNC_AT) is not None


@pytest.mark.asyncio
async def test_run_with_empty_response_still_marks_last_sync(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returned nothing — we still record that we ran so the UI's
    ``synced N hours ago`` doesn't get stuck."""
    monkeypatch.setattr(mod, "fetch_upcoming_industry_events", _stub_fetch([]))

    result = await run_industry_gemini_sync(db_session, api_key="fake-key", as_of=date(2026, 5, 31))
    assert result.skipped_reason is None
    assert result.events_returned == 0
    assert result.rows_upserted == 0
    metadata = SystemMetadataRepository(db_session)
    assert metadata.get_datetime(KEY_LAST_INDUSTRY_SYNC_AT) is not None


# --- budget guard --------------------------------------------------------


@pytest.mark.asyncio
async def test_run_skips_when_daily_budget_exhausted(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set the counter at the cap → next run is skipped without an LLM call."""
    today = date(2026, 5, 31)
    metadata = SystemMetadataRepository(db_session)
    metadata.set(
        KEY_GEMINI_REQUESTS_BUDGET,
        f"{today.isoformat()}:{mod._LLM_USAGE_BUDGET_REQUESTS_PER_DAY}",
    )
    db_session.flush()

    called = False

    async def _should_not_call(**_: Any) -> list[CalendarEventRow]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(mod, "fetch_upcoming_industry_events", _should_not_call)

    result = await run_industry_gemini_sync(db_session, api_key="fake-key", as_of=today)
    assert result.skipped_reason == "daily_budget_exhausted"
    assert called is False


@pytest.mark.asyncio
async def test_run_bumps_counter_on_each_call(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "fetch_upcoming_industry_events", _stub_fetch([]))
    today = date(2026, 5, 31)
    for _ in range(3):
        await run_industry_gemini_sync(db_session, api_key="fake-key", as_of=today)
    raw = SystemMetadataRepository(db_session).get(KEY_GEMINI_REQUESTS_BUDGET)
    assert raw == f"{today.isoformat()}:3"


@pytest.mark.asyncio
async def test_budget_counter_resets_when_day_rolls_over(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yesterday's count must not block today — the counter is keyed by
    ``YYYY-MM-DD`` so old entries are implicitly discarded."""
    metadata = SystemMetadataRepository(db_session)
    metadata.set(
        KEY_GEMINI_REQUESTS_BUDGET,
        f"2026-05-30:{mod._LLM_USAGE_BUDGET_REQUESTS_PER_DAY}",
    )
    db_session.flush()

    monkeypatch.setattr(mod, "fetch_upcoming_industry_events", _stub_fetch([]))
    result = await run_industry_gemini_sync(db_session, api_key="fake-key", as_of=date(2026, 5, 31))
    assert result.skipped_reason is None
    # Counter resets to 1 today.
    raw = metadata.get(KEY_GEMINI_REQUESTS_BUDGET)
    assert raw == "2026-05-31:1"


def test_budget_counter_tolerates_malformed_value(db_session: Session) -> None:
    metadata = SystemMetadataRepository(db_session)
    metadata.set(KEY_GEMINI_REQUESTS_BUDGET, "totally:garbled:contents")
    db_session.flush()
    # Should treat malformed as "no usage" and not raise.
    assert mod._budget_exhausted(metadata, today=date(2026, 5, 31)) is False

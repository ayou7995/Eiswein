"""Tests for :mod:`app.jobs.industry_sync` — APScheduler wrapper."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.jobs import industry_sync as industry_sync_job


@pytest.mark.asyncio
async def test_run_returns_false_when_api_key_missing(
    settings: Settings,
    session_factory: sessionmaker[OrmSession],
) -> None:
    """No key → ingestion returns skipped_reason; wrapper logs and
    returns False so APScheduler can record the skip in the job audit."""
    ok = await industry_sync_job.run(session_factory=session_factory, settings=settings)
    assert ok is False


@pytest.mark.asyncio
async def test_run_returns_true_on_successful_sync(
    settings: Settings,
    session_factory: sessionmaker[OrmSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM call succeeds (mocked) and the API key is configured,
    the wrapper hands the session through, commits, and returns True."""
    settings_with_key = settings.model_copy(update={"gemini_api_key": SecretStr("fake-key")})

    async def _fake_run(session: Any, *, api_key: str, as_of: Any = None) -> Any:
        from app.ingestion.industry_gemini_sync import IndustryGeminiSyncResult

        return IndustryGeminiSyncResult(skipped_reason=None, events_returned=2, rows_upserted=2)

    monkeypatch.setattr("app.jobs.industry_sync.run_industry_gemini_sync", _fake_run)

    ok = await industry_sync_job.run(session_factory=session_factory, settings=settings_with_key)
    assert ok is True


@pytest.mark.asyncio
async def test_run_swallows_unhandled_exceptions(
    settings: Settings,
    session_factory: sessionmaker[OrmSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler protocol: ``run`` must never raise — surprise errors
    have to surface in logs, not crash the scheduler loop."""
    settings_with_key = settings.model_copy(update={"gemini_api_key": SecretStr("fake-key")})

    async def _explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("upstream went sideways")

    monkeypatch.setattr("app.jobs.industry_sync.run_industry_gemini_sync", _explode)
    ok = await industry_sync_job.run(session_factory=session_factory, settings=settings_with_key)
    assert ok is False

"""Paste-driven industry sync ingestion — parse + upsert + last-sync stamp."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.system_metadata_repository import SystemMetadataRepository
from app.ingestion.industry_gemini_sync import (
    KEY_LAST_INDUSTRY_SYNC_AT,
    import_industry_events_from_paste,
)

_VALID_PASTE = """[
  {
    "registry_id": 1,
    "name": "NVIDIA GTC 2027",
    "start_date": "2027-03-15",
    "end_date": "2027-03-19",
    "confidence": "confirmed",
    "source_url": "https://www.nvidia.com/gtc/",
    "notes": "Listed on NVIDIA GTC homepage."
  },
  {
    "registry_id": 9,
    "name": "Apple WWDC 2026 Keynote",
    "start_date": "2026-06-08",
    "confidence": "estimated",
    "source_url": null,
    "notes": "Historically first Monday of June."
  }
]"""


def test_import_handles_empty_paste(db_session: Session) -> None:
    """Whitespace-only paste short-circuits without an upsert call."""
    result = import_industry_events_from_paste(db_session, raw_json_text="   ")
    assert result.parsed_count == 0
    assert result.rows_upserted == 0
    # Empty paste must NOT mark the last_sync_at — otherwise the UI's
    # staleness counter would lie ("just synced!" when nothing happened).
    assert SystemMetadataRepository(db_session).get_datetime(KEY_LAST_INDUSTRY_SYNC_AT) is None


def test_import_writes_rows_and_records_last_sync(db_session: Session) -> None:
    result = import_industry_events_from_paste(db_session, raw_json_text=_VALID_PASTE)
    assert result.parsed_count == 2
    assert result.rows_upserted == 2

    metadata = SystemMetadataRepository(db_session)
    assert metadata.get_datetime(KEY_LAST_INDUSTRY_SYNC_AT) is not None


def test_import_garbage_paste_still_marks_last_sync(db_session: Session) -> None:
    """Even when the paste is unparseable, we update last_sync_at so the
    UI's "synced N hours ago" reflects the most recent paste attempt."""
    result = import_industry_events_from_paste(db_session, raw_json_text="definitely not JSON")
    assert result.parsed_count == 0
    assert result.rows_upserted == 0
    metadata = SystemMetadataRepository(db_session)
    assert metadata.get_datetime(KEY_LAST_INDUSTRY_SYNC_AT) is not None


def test_import_is_idempotent_on_repeat(db_session: Session) -> None:
    """Pasting the same JSON twice doesn't duplicate rows — the unique
    index on (date, type, ticker, title) deduplicates."""
    first = import_industry_events_from_paste(db_session, raw_json_text=_VALID_PASTE)
    second = import_industry_events_from_paste(db_session, raw_json_text=_VALID_PASTE)
    assert first.rows_upserted == 2
    # Upsert counts include UPDATE branch, so second run also reports 2;
    # what we really care about is that the DB doesn't grow.
    assert second.rows_upserted == 2

    from app.db.models import CalendarEvent

    count = db_session.query(CalendarEvent).filter(CalendarEvent.source == "gemini").count()
    assert count == 2


@pytest.mark.parametrize(
    "bad_paste",
    [
        '{"not": "an array"}',
        "[]",
        '[{"registry_id": 1, "name": "X"}]',  # missing start_date + confidence
        "definitely not JSON",
    ],
)
def test_import_tolerates_bad_inputs_without_raising(db_session: Session, bad_paste: str) -> None:
    """Every problematic shape returns ``parsed_count=0`` rather than
    raising — the caller is an HTTP handler that should return 200."""
    result = import_industry_events_from_paste(db_session, raw_json_text=bad_paste)
    assert result.parsed_count == 0
    assert result.rows_upserted == 0

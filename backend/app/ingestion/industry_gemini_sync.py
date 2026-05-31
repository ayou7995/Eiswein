"""Paste-driven industry catalyst ingestion.

The original design called the Gemini API directly. After an SDK bug
that swallowed grounded responses (``parts=null`` despite generated
tokens), we pivoted to a manual paste flow: the operator runs the
prompt in https://aistudio.google.com and pastes the JSON output into
the Settings UI. This module wraps the per-paste validate + upsert
step.

Side effects:
* Upserts rows into ``calendar_event``.
* Writes ``last_industry_sync_at`` to SystemMetadata so the UI can render
  "上次同步: N 小時前" without re-deriving it from row contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.datasources.gemini_industry_source import parse_industry_events_text
from app.db.repositories.calendar_event_repository import CalendarEventRepository
from app.db.repositories.system_metadata_repository import SystemMetadataRepository

logger = structlog.get_logger("eiswein.ingestion.industry_gemini_sync")

# SystemMetadata key (single source of truth so a typo doesn't shadow
# writes from another caller).
KEY_LAST_INDUSTRY_SYNC_AT: Final[str] = "last_industry_sync_at"


@dataclass(frozen=True)
class IndustryGeminiImportResult:
    """Audit shape for one paste."""

    parsed_count: int
    rows_upserted: int


def import_industry_events_from_paste(
    session: Session,
    *,
    raw_json_text: str,
) -> IndustryGeminiImportResult:
    """Validate the operator-pasted JSON and upsert rows.

    Caller commits the session. An empty / malformed paste returns
    ``parsed_count=0`` — endpoint layer surfaces that as a UI message
    rather than a 4xx, because the most likely cause is the operator
    pasting an incomplete chunk."""
    if not raw_json_text.strip():
        return IndustryGeminiImportResult(parsed_count=0, rows_upserted=0)

    rows = parse_industry_events_text(raw_json_text)
    upserted = 0
    if rows:
        repo = CalendarEventRepository(session)
        upserted = repo.upsert_many(rows)

    metadata = SystemMetadataRepository(session)
    metadata.set_datetime(KEY_LAST_INDUSTRY_SYNC_AT, datetime.now(UTC))

    logger.info(
        "industry_sync_paste_complete",
        parsed=len(rows),
        rows_upserted=upserted,
    )
    return IndustryGeminiImportResult(parsed_count=len(rows), rows_upserted=upserted)


__all__ = [
    "KEY_LAST_INDUSTRY_SYNC_AT",
    "IndustryGeminiImportResult",
    "import_industry_events_from_paste",
]

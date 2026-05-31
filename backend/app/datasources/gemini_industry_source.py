"""Gemini-assisted industry event sync (manual paste mode).

Originally this module called the Gemini API directly via google-genai
+ grounded search. After four iterations against ``google-genai==0.7.0``
we hit a hard SDK bug: ``gemini-2.5-flash-lite + Tool(google_search)``
returned ``finish_reason=STOP, candidates_token_count=295, parts=null``
— the model generated content but the SDK packaged it with empty parts,
making the response unparseable. The pre-1.0 SDK API churn made bumping
versions a risk multiplier, so we pivoted to a manual paste flow.

The current shape:

1. Operator opens Settings → Industry Sync card → clicks "複製 prompt".
   :func:`build_industry_sync_prompt` renders the prompt from the live
   :data:`CONFERENCES` registry + today's date.
2. Operator pastes prompt into https://aistudio.google.com (browser UI
   uses a stable Gemini call path that doesn't suffer the SDK bug),
   grabs the JSON output.
3. Operator pastes JSON back into the Settings textarea → submit.
4. Backend calls :func:`parse_industry_events_text`, validates per
   :class:`IndustryEventResponse`, and returns rows ready for
   ``CalendarEventRepository.upsert_many``.

The prompt + Pydantic schema + per-entry payload conversion are all
shared with the (now-retired) direct-API path, so flipping back to
auto-sync later is a small refactor — just re-add the LLM client and
wire ``parse_industry_events_text`` to its output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.datasources._industry_conference_registry import (
    CONFERENCES,
    ConferenceSource,
)
from app.db.repositories.calendar_event_repository import CalendarEventRow

logger = structlog.get_logger("eiswein.datasources.gemini_industry")

_SOURCE_NAME: Final[str] = "gemini"

_CONFIDENCE_VALUES: Final[frozenset[str]] = frozenset({"confirmed", "estimated", "uncertain"})


class IndustryEventResponse(BaseModel):
    """Validated shape of one LLM-returned conference entry.

    ``registry_id`` is the 1-based ordinal we gave the LLM in the prompt;
    it's the stable identifier we use to look the ConferenceSource back
    up. Substring matching on names was fragile because the LLM injects
    year tokens mid-name ("Apple WWDC 2026 Keynote") and that breaks
    naive substring on the registry name "Apple WWDC Keynote"."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    registry_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    confidence: str
    source_url: str | None = None
    notes: str | None = Field(default=None, max_length=500)


def build_industry_sync_prompt(
    *,
    as_of: date | None = None,
    conferences: Sequence[ConferenceSource] = CONFERENCES,
) -> str:
    """Render the paste-ready prompt.

    Same string we used to send to the API — keeps the registry as
    source of truth and means a registry edit propagates to the next
    UI render without code change."""
    today = as_of or datetime.now(UTC).date()
    lines = [
        f"You maintain a tech industry event calendar. Today's date is {today.isoformat()}.",
        "",
        "For each conference below, use Google Search grounding to find the NEXT",
        f"scheduled occurrence between {today.isoformat()} and "
        f"{(today.replace(year=today.year + 1)).isoformat()}.",
        "",
        "Rules:",
        "- Prefer OFFICIAL announcements (event homepage, organizer press release).",
        "  Wikipedia is acceptable as a secondary source when official sites are silent.",
        '- If an official confirmed date is found: confidence="confirmed", include source_url.',
        '- If only historical pattern (last 3 years) suggests a window: confidence="estimated",',
        "  source_url may be null, pick the most likely date inside the typical window.",
        '- If sources disagree or grounding finds nothing useful: confidence="uncertain".',
        "- Skip any conference whose next iteration is already past or unannounced",
        "  beyond 12 months.",
        "- end_date is optional — set it for multi-day events only.",
        '- name should include the year (e.g. "Computex 2027", "Apple WWDC 2026 Keynote").',
        "",
        "Return ONLY a JSON array of objects matching this schema (no prose, no markdown fence):",
        "[",
        "  {",
        '    "registry_id": 1,  // echo back the number from the list below',
        '    "name": "Computex 2027",  // include the year in the display name',
        '    "start_date": "YYYY-MM-DD",',
        '    "end_date": "YYYY-MM-DD" | null,',
        '    "confidence": "confirmed" | "estimated" | "uncertain",',
        '    "source_url": "https://..." | null,',
        '    "notes": "brief justification"',
        "  },",
        "  ...",
        "]",
        "",
        "Conferences to look up (echo registry_id in your response):",
    ]
    for idx, conf in enumerate(conferences, start=1):
        primary = f" — tracks {conf.primary_ticker}" if conf.primary_ticker else ""
        lines.append(
            f"{idx}. {conf.name} (organizer: {conf.organizer};"
            f" typical: {conf.typical_window}){primary}"
        )
    return "\n".join(lines)


def parse_industry_events_text(
    raw_text: str,
    *,
    verified_at: datetime | None = None,
    conferences: Sequence[ConferenceSource] = CONFERENCES,
) -> list[CalendarEventRow]:
    """Validate the LLM JSON payload and convert it to calendar rows.

    Used by the ``POST /calendar/industry-sync/import`` endpoint. The
    parsing layer is forgiving: whole-batch failures (raw isn't JSON
    at all) return an empty list with a warning log; per-entry failures
    skip just that entry. ``verified_at`` defaults to ``now()`` so the
    UI staleness banner counts from the moment the operator pasted —
    not from when the operator opened Gemini."""
    parsed = _parse_response_text(raw_text)
    when_verified = verified_at or datetime.now(UTC)
    rows = [
        _to_calendar_row(
            entry,
            matched_conference=_match_conference(entry.registry_id, conferences),
            verified_at=when_verified,
        )
        for entry in parsed
    ]
    logger.info(
        "gemini_industry_paste_parsed",
        returned=len(parsed),
        rows=len(rows),
    )
    return rows


def _strip_markdown_fences(raw: str) -> str:
    """Gemini occasionally wraps JSON in ```json fences. Strip them so
    ``json.loads`` can parse the body without the operator having to
    clean the paste by hand."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _parse_response_text(raw_text: str) -> list[IndustryEventResponse]:
    """Validate the paste payload into typed event objects.

    Whole-batch failures (raw is not valid JSON) return ``[]`` with a
    log so the import endpoint can surface a clean error to the UI.
    Per-entry failures (one bad confidence value, missing date) log
    the row index and continue, so a flaky single entry doesn't wipe
    out the batch."""
    text = _strip_markdown_fences(raw_text)
    try:
        decoded: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(
            "gemini_industry_response_unparseable",
            error=str(exc),
            preview=text[:200],
        )
        return []
    if not isinstance(decoded, list):
        logger.warning(
            "gemini_industry_response_not_array",
            actual_type=type(decoded).__name__,
        )
        return []

    valid: list[IndustryEventResponse] = []
    for index, entry in enumerate(decoded):
        if not isinstance(entry, dict):
            logger.warning("gemini_industry_entry_not_object", ordinal=index)
            continue
        try:
            parsed = IndustryEventResponse.model_validate(entry)
        except ValidationError as exc:
            logger.warning(
                "gemini_industry_entry_invalid",
                ordinal=index,
                error=str(exc),
                name=entry.get("name"),
            )
            continue
        if parsed.confidence not in _CONFIDENCE_VALUES:
            logger.warning(
                "gemini_industry_entry_bad_confidence",
                ordinal=index,
                name=parsed.name,
                confidence=parsed.confidence,
            )
            continue
        valid.append(parsed)
    return valid


def _to_calendar_row(
    response: IndustryEventResponse,
    *,
    matched_conference: ConferenceSource | None,
    verified_at: datetime,
) -> CalendarEventRow:
    """Convert one validated entry into a calendar_event row."""
    payload: dict[str, Any] = {
        "confidence": response.confidence,
        "last_verified_at": verified_at.isoformat(),
    }
    if response.source_url:
        payload["source_url"] = response.source_url
    if response.end_date:
        payload["end_date"] = response.end_date.isoformat()
    if response.notes:
        payload["notes"] = response.notes
    if matched_conference and matched_conference.tags:
        payload["tags"] = list(matched_conference.tags)
    ticker = matched_conference.primary_ticker if matched_conference else None
    return CalendarEventRow(
        event_date=response.start_date,
        event_time=None,
        type="industry",
        ticker_symbol=ticker,
        title=response.name,
        payload_json=payload,
        source=_SOURCE_NAME,
    )


def _match_conference(
    registry_id: int, conferences: Sequence[ConferenceSource]
) -> ConferenceSource | None:
    """Look up the source row by the 1-based ordinal we sent in the prompt.

    Using the index keeps matching exact even when the LLM rewrites the
    display name to include the year ("Apple WWDC 2026 Keynote") or
    drops the parenthesised disambiguator from our registry."""
    idx = registry_id - 1
    if 0 <= idx < len(conferences):
        return conferences[idx]
    return None


__all__ = [
    "IndustryEventResponse",
    "build_industry_sync_prompt",
    "parse_industry_events_text",
]

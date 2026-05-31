"""Gemini-backed industry event sync.

The free industry-event YAML feeder needs operator effort to stay fresh —
this module replaces that by asking Gemini 2.0 Flash + Google Search
grounding for the next confirmed date of every conference in
:mod:`_industry_conference_registry`. One batched prompt per weekly sync
keeps API usage trivially within the Google AI Studio free tier
(1500 RPD); the per-event response includes a confidence level and the
official source URL so the UI can render trust signals.

The result is a list of :class:`CalendarEventRow` dicts ready for
:meth:`CalendarEventRepository.upsert_many`, identical to the shape the
YAML loader emits — calendar_sync treats us as just another feeder.

Failure modes are all graceful:
* No ``GEMINI_API_KEY`` → :func:`fetch_upcoming_industry_events` returns ``[]``.
* Network / quota error → tenacity retries, then ``[]`` (existing DB rows
  untouched, daily_update logs a warning).
* Malformed LLM JSON → per-entry validation drops bad rows, keeps good
  rows. Total wipe-out only happens if the whole batch is unparseable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.datasources._industry_conference_registry import (
    CONFERENCES,
    ConferenceSource,
)
from app.db.repositories.calendar_event_repository import CalendarEventRow

logger = structlog.get_logger("eiswein.datasources.gemini_industry")

# Model + grounding tool — pinned strings so a Gemini SDK upgrade doesn't
# silently switch model behaviour. Bump deliberately when the user wants.
#
# Why ``gemini-2.5-flash-lite``:
# * ``gemini-2.0-flash`` — Google moved off free tier in 2026 (limit: 0).
# * ``gemini-2.5-flash`` — works on free tier (5 RPM / 250 RPD) BUT ships
#   with thinking mode on by default, which spends output tokens on
#   internal reasoning. With grounded search also bloating the response,
#   the 25-entry batch JSON gets truncated mid-way (observed: 1 of 25
#   returned). ``google-genai==0.7.0``'s ``ThinkingConfig`` lacks the
#   ``thinking_budget`` field we'd need to disable thinking explicitly.
# * ``gemini-2.5-flash-lite`` — thinking OFF by default, supports
#   ``google_search`` grounding, free tier is even better (15 RPM /
#   1000 RPD). Right fit for structured extraction.
_MODEL: Final[str] = "gemini-2.5-flash-lite"

# Max retries against the LLM call before we give up for this sync run.
# A 429 from Google's free tier is rare at our volume (~4 req/month) but
# we still want a backoff envelope so a transient network blip doesn't
# blank the feeder.
_MAX_RETRIES: Final[int] = 3

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


def _build_prompt(*, as_of: date, conferences: Sequence[ConferenceSource]) -> str:
    """Compose the batch prompt sent to Gemini.

    Conference rows are emitted with their organizer + typical window so
    grounded search can disambiguate (e.g. Microsoft has Build and Ignite
    in the same calendar year — naming both helps the LLM not confuse
    them)."""
    lines = [
        f"You maintain a tech industry event calendar. Today's date is {as_of.isoformat()}.",
        "",
        "For each conference below, use Google Search grounding to find the NEXT",
        f"scheduled occurrence between {as_of.isoformat()} and "
        f"{(as_of.replace(year=as_of.year + 1)).isoformat()}.",
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


def _is_transient_gemini_error(exc: BaseException) -> bool:
    """Retry network blips + Google's 429 / 503 transient responses.

    The google-genai SDK surfaces HTTP errors with the status code in the
    exception class name (``ResourceExhausted``, ``ServiceUnavailable``,
    ``DeadlineExceeded``, ``InternalServerError``) or message body. We
    match by string fragment so we don't have to bind to specific SDK
    exception classes that may rename across releases."""
    if isinstance(exc, ConnectionError | TimeoutError | OSError):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "429",
            "rate limit",
            "resource exhausted",
            "503",
            "service unavailable",
            "deadline exceeded",
            "internal server error",
        )
    )


def _strip_markdown_fences(raw: str) -> str:
    """Gemini sometimes wraps JSON in ```json fences despite instructions.
    Strip the fences if present so json.loads can parse the body."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _parse_response_text(raw_text: str) -> list[IndustryEventResponse]:
    """Validate the LLM response into typed event objects.

    Whole-batch failures (raw is not valid JSON) return ``[]`` with a
    log so the sync degrades gracefully. Per-entry failures
    (one bad confidence value, missing date) log the row index and
    continue, so a flaky single entry doesn't wipe out the batch."""
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
    """Convert one validated LLM response into a calendar_event row."""
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


async def fetch_upcoming_industry_events(
    *,
    api_key: str,
    as_of: date | None = None,
    conferences: Sequence[ConferenceSource] = CONFERENCES,
) -> list[CalendarEventRow]:
    """Ask Gemini for upcoming industry-conference dates.

    Returns rows ready for :meth:`CalendarEventRepository.upsert_many`.
    On any failure (empty key, network, malformed response) returns ``[]``
    and logs a structured warning — caller treats empty result as
    "leave existing DB rows untouched"."""
    if not api_key:
        logger.info("gemini_industry_skipped_no_key")
        return []
    if not conferences:
        return []

    today = as_of or datetime.now(UTC).date()
    prompt = _build_prompt(as_of=today, conferences=conferences)

    try:
        raw_text = await _invoke_gemini_with_retry(api_key=api_key, prompt=prompt)
    except Exception as exc:
        logger.warning(
            "gemini_industry_call_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return []

    parsed = _parse_response_text(raw_text)
    verified_at = datetime.now(UTC)
    rows = [
        _to_calendar_row(
            entry,
            matched_conference=_match_conference(entry.registry_id, conferences),
            verified_at=verified_at,
        )
        for entry in parsed
    ]
    logger.info(
        "gemini_industry_sync_parsed",
        requested=len(conferences),
        returned=len(parsed),
        rows=len(rows),
    )
    return rows


async def _invoke_gemini_with_retry(*, api_key: str, prompt: str) -> str:
    """Call Gemini Flash with grounded search, retrying transient errors.

    Returns the raw text payload. Caller is responsible for JSON parsing
    so retry decisions stay separate from validation decisions."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential_jitter(initial=2, max=30),
        retry=retry_if_exception(_is_transient_gemini_error),
        reraise=True,
    ):
        with attempt:
            return await _call_gemini_once(api_key=api_key, prompt=prompt)
    raise RuntimeError("AsyncRetrying exited without raising or returning")


async def _call_gemini_once(*, api_key: str, prompt: str) -> str:
    """Single Gemini request. Imports the SDK lazily so test runs that
    monkeypatch this function don't import the heavy SDK at all, and so
    a missing ``google-genai`` install fails loudly at call-time rather
    than at module import (keeping the FastAPI startup cheap)."""
    from google import genai  # type: ignore[import-untyped]
    from google.genai import types as genai_types  # type: ignore[import-untyped]

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            temperature=0.1,
        ),
    )
    text = _extract_response_text(response)
    # INFO (not DEBUG) so the response size is visible without changing
    # log levels — useful while diagnosing per-batch truncation.
    logger.info("gemini_industry_raw_response", chars=len(text))
    return text


def _extract_response_text(response: object) -> str:
    """Pull concatenated text out of a Gemini response.

    ``response.text`` is a convenience that returns ``None`` for several
    real-world cases on grounded responses:
    * The text lives split across multiple ``content.parts`` entries
      (grounded answers package citations as separate parts).
    * The response was blocked by safety filters (no parts at all).
    * ``finish_reason`` was MAX_TOKENS partway through a part.

    Walking ``candidates[0].content.parts`` and stringifying every part
    that has a ``text`` attr is more robust. On total failure we log
    enough metadata (candidates count, finish reasons, block reason) so
    the operator can tell "safety block" from "empty response" from
    "API hiccup" without enabling debug logging."""
    raw_text = getattr(response, "text", None)
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text

    candidates = getattr(response, "candidates", None) or []
    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str):
                chunks.append(part_text)

    if chunks:
        return "".join(chunks)

    feedback = getattr(response, "prompt_feedback", None)
    logger.warning(
        "gemini_industry_response_empty",
        candidates=len(candidates),
        finish_reasons=[str(getattr(c, "finish_reason", None)) for c in candidates],
        block_reason=str(getattr(feedback, "block_reason", None)) if feedback is not None else None,
    )
    raise ValueError("gemini response had no text parts")


__all__ = [
    "IndustryEventResponse",
    "fetch_upcoming_industry_events",
]

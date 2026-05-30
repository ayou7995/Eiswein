"""GeminiIndustrySource — mocked LLM roundtrip + parsing + retry."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.datasources import gemini_industry_source as mod
from app.datasources._industry_conference_registry import (
    CONFERENCES,
    ConferenceSource,
)
from app.datasources.gemini_industry_source import (
    IndustryEventResponse,
    fetch_upcoming_industry_events,
)

# registry_id values reference CONFERENCES order (1-based):
#   1 = NVIDIA GTC Spring,  3 = Computex Taipei,  9 = Apple WWDC Keynote
_VALID_LLM_RESPONSE = """[
  {
    "registry_id": 3,
    "name": "Computex 2027",
    "start_date": "2027-05-25",
    "end_date": "2027-05-28",
    "confidence": "confirmed",
    "source_url": "https://www.computextaipei.com.tw/",
    "notes": "Announced by TAITRA on official site."
  },
  {
    "registry_id": 1,
    "name": "NVIDIA GTC 2027 (Spring)",
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
    "end_date": null,
    "confidence": "estimated",
    "source_url": null,
    "notes": "Historically first or second Monday of June."
  }
]"""


# --- helpers --------------------------------------------------------------


def _patch_invoke(monkeypatch: pytest.MonkeyPatch, *, payload: str) -> None:
    """Stub :func:`_invoke_gemini_with_retry` so tests never hit the network
    or import the heavy google-genai SDK."""

    async def _fake(*, api_key: str, prompt: str) -> str:
        return payload

    monkeypatch.setattr(mod, "_invoke_gemini_with_retry", _fake)


# --- happy path ----------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_rows_for_valid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_invoke(monkeypatch, payload=_VALID_LLM_RESPONSE)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert len(rows) == 3
    # Each row uses the registry "industry" type and gemini source.
    for row in rows:
        assert row["type"] == "industry"
        assert row["source"] == "gemini"
        payload = row["payload_json"]
        assert payload is not None
        assert "confidence" in payload
        assert "last_verified_at" in payload


@pytest.mark.asyncio
async def test_fetch_attaches_primary_ticker_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM names include the year; the matcher strips it and looks up
    the registry entry by substring so primary_ticker / tags follow."""
    _patch_invoke(monkeypatch, payload=_VALID_LLM_RESPONSE)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    by_title = {row["title"]: row for row in rows}
    # WWDC → AAPL; GTC → NVDA; Computex → None (no primary ticker).
    assert by_title["Apple WWDC 2026 Keynote"]["ticker_symbol"] == "AAPL"
    assert by_title["NVIDIA GTC 2027 (Spring)"]["ticker_symbol"] == "NVDA"
    assert by_title["Computex 2027"]["ticker_symbol"] is None


@pytest.mark.asyncio
async def test_fetch_payload_carries_source_url_and_end_date_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_invoke(monkeypatch, payload=_VALID_LLM_RESPONSE)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    by_title = {row["title"]: row for row in rows}
    computex_payload = by_title["Computex 2027"]["payload_json"]
    assert computex_payload is not None
    assert computex_payload["source_url"] == "https://www.computextaipei.com.tw/"
    assert computex_payload["end_date"] == "2027-05-28"
    # WWDC is single-day (end_date null) so the key is absent.
    wwdc_payload = by_title["Apple WWDC 2026 Keynote"]["payload_json"]
    assert wwdc_payload is not None
    assert "end_date" not in wwdc_payload
    assert "source_url" not in wwdc_payload


# --- empty / no-key ------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_api_key_missing() -> None:
    """No key → no LLM call, no error — caller treats as "feeder disabled"."""
    rows = await fetch_upcoming_industry_events(api_key="", as_of=date(2026, 5, 31))
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_no_conferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty registry → skip LLM call entirely (avoids token waste)."""
    called = False

    async def _should_not_call(**_: Any) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(mod, "_invoke_gemini_with_retry", _should_not_call)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", conferences=())
    assert rows == []
    assert called is False


# --- malformed responses -------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_unparseable_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_invoke(monkeypatch, payload="this is definitely not JSON {[")
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_response_is_not_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_invoke(monkeypatch, payload='{"events": []}')
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_strips_markdown_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini occasionally wraps JSON in ```json fences despite the prompt
    asking for raw JSON. We strip them so the batch isn't lost."""
    fenced = "```json\n" + _VALID_LLM_RESPONSE + "\n```"
    _patch_invoke(monkeypatch, payload=fenced)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_fetch_drops_only_bad_entries_keeps_good_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One row with an unknown confidence shouldn't taint the batch."""
    payload = """[
      {
        "registry_id": 3,
        "name": "Computex 2027",
        "start_date": "2027-05-25",
        "confidence": "totally-made-up",
        "source_url": null
      },
      {
        "registry_id": 9,
        "name": "Apple WWDC 2026 Keynote",
        "start_date": "2026-06-08",
        "confidence": "estimated",
        "source_url": null
      },
      {
        "registry_id": 99,
        "name": "Missing date event",
        "confidence": "confirmed"
      }
    ]"""
    _patch_invoke(monkeypatch, payload=payload)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    # Only the WWDC row survives — the other two trip schema validation.
    assert len(rows) == 1
    assert rows[0]["title"] == "Apple WWDC 2026 Keynote"


@pytest.mark.asyncio
async def test_fetch_accepts_uncertain_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'uncertain' is a legitimate signal the UI uses — must not be dropped."""
    payload = """[
      {
        "registry_id": 3,
        "name": "Computex 2027",
        "start_date": "2027-05-25",
        "confidence": "uncertain",
        "source_url": null,
        "notes": "Conflicting sources."
      }
    ]"""
    _patch_invoke(monkeypatch, payload=payload)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert len(rows) == 1
    payload_dict = rows[0]["payload_json"]
    assert payload_dict is not None
    assert payload_dict["confidence"] == "uncertain"


# --- network / quota error handling --------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_llm_call_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any unhandled exception from the LLM call is swallowed so the
    weekly sync degrades gracefully (existing DB rows stay put)."""

    async def _explode(**_: Any) -> str:
        raise RuntimeError("upstream blew up")

    monkeypatch.setattr(mod, "_invoke_gemini_with_retry", _explode)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    assert rows == []


def test_transient_error_predicate_matches_rate_limit_strings() -> None:
    """Sanity-check the substring matcher used by the retry filter."""
    assert mod._is_transient_gemini_error(ValueError("429 Too Many Requests"))
    assert mod._is_transient_gemini_error(RuntimeError("Resource exhausted"))
    assert mod._is_transient_gemini_error(RuntimeError("503 Service Unavailable"))
    assert mod._is_transient_gemini_error(ConnectionError("dropped socket"))
    # Real validation errors (LLM lied about date format) should NOT retry —
    # retrying won't help and would burn quota.
    assert not mod._is_transient_gemini_error(ValueError("invalid date format"))


# --- registry sanity -----------------------------------------------------


def test_conference_registry_is_non_empty_and_typed() -> None:
    assert len(CONFERENCES) >= 20
    for conf in CONFERENCES:
        assert isinstance(conf, ConferenceSource)
        assert conf.name.strip()
        assert conf.organizer.strip()
        assert conf.typical_window.strip()


def test_industry_event_response_validates_strict() -> None:
    """Pydantic should accept the minimum payload + reject missing date."""
    minimal = IndustryEventResponse.model_validate(
        {
            "registry_id": 1,
            "name": "X",
            "start_date": "2027-01-01",
            "confidence": "confirmed",
        }
    )
    assert minimal.start_date == date(2027, 1, 1)

    import pydantic

    with pytest.raises(pydantic.ValidationError):
        IndustryEventResponse.model_validate({"name": "X", "confidence": "confirmed"})


# --- end-to-end timestamp wiring -----------------------------------------


@pytest.mark.asyncio
async def test_fetch_writes_last_verified_at_in_iso_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_invoke(monkeypatch, payload=_VALID_LLM_RESPONSE)
    before = datetime.now(UTC)
    rows = await fetch_upcoming_industry_events(api_key="fake-key", as_of=date(2026, 5, 31))
    after = datetime.now(UTC)
    for row in rows:
        payload = row["payload_json"]
        assert payload is not None
        verified_at_str = payload["last_verified_at"]
        verified_at = datetime.fromisoformat(verified_at_str)
        assert before <= verified_at <= after

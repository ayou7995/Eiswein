"""Gemini paste flow — prompt builder + JSON parser + row converter."""

from __future__ import annotations

from datetime import date

import pytest

from app.datasources._industry_conference_registry import (
    CONFERENCES,
    ConferenceSource,
)
from app.datasources.gemini_industry_source import (
    IndustryEventResponse,
    build_industry_sync_prompt,
    parse_industry_events_text,
)

# registry_id values reference CONFERENCES order (1-based):
#   1 = NVIDIA GTC Spring,  3 = Computex Taipei,  9 = Apple WWDC Keynote
_VALID_PASTE = """[
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


# --- Prompt builder ------------------------------------------------------


def test_prompt_includes_registry_entries() -> None:
    prompt = build_industry_sync_prompt(as_of=date(2026, 5, 31))
    # Spot-check a handful of conference names.
    assert "NVIDIA GTC" in prompt
    assert "Computex Taipei" in prompt
    assert "Apple WWDC Keynote" in prompt
    # Schema cues the LLM needs to follow.
    assert "registry_id" in prompt
    assert "confidence" in prompt
    # Today's date is interpolated so the LLM knows the forward window.
    assert "2026-05-31" in prompt


def test_prompt_renders_with_default_as_of() -> None:
    """Omitting ``as_of`` falls back to today — the prompt still
    contains a valid ISO date somewhere."""
    prompt = build_industry_sync_prompt()
    import re

    assert re.search(r"\d{4}-\d{2}-\d{2}", prompt) is not None


# --- Parser --------------------------------------------------------------


def test_parser_returns_rows_for_valid_paste() -> None:
    rows = parse_industry_events_text(_VALID_PASTE)
    assert len(rows) == 3
    for row in rows:
        assert row["type"] == "industry"
        assert row["source"] == "gemini"
        payload = row["payload_json"]
        assert payload is not None
        assert "confidence" in payload
        assert "last_verified_at" in payload


def test_parser_attaches_primary_ticker_from_registry() -> None:
    """``registry_id`` lookups attach the registry's ``primary_ticker``
    + ``tags`` so WWDC → AAPL etc."""
    rows = parse_industry_events_text(_VALID_PASTE)
    by_title = {row["title"]: row for row in rows}
    assert by_title["Apple WWDC 2026 Keynote"]["ticker_symbol"] == "AAPL"
    assert by_title["NVIDIA GTC 2027 (Spring)"]["ticker_symbol"] == "NVDA"
    # Computex has no primary ticker in the registry.
    assert by_title["Computex 2027"]["ticker_symbol"] is None


def test_parser_carries_source_url_and_end_date_when_present() -> None:
    rows = parse_industry_events_text(_VALID_PASTE)
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


def test_parser_returns_empty_on_unparseable_json() -> None:
    rows = parse_industry_events_text("this is definitely not JSON {[")
    assert rows == []


def test_parser_returns_empty_when_response_is_not_array() -> None:
    rows = parse_industry_events_text('{"events": []}')
    assert rows == []


def test_parser_strips_markdown_fences() -> None:
    """Gemini occasionally wraps JSON in ```json fences despite the prompt."""
    fenced = "```json\n" + _VALID_PASTE + "\n```"
    rows = parse_industry_events_text(fenced)
    assert len(rows) == 3


def test_parser_drops_only_bad_entries_keeps_good_ones() -> None:
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
    rows = parse_industry_events_text(payload)
    # Only the WWDC row survives — the other two trip schema validation.
    assert len(rows) == 1
    assert rows[0]["title"] == "Apple WWDC 2026 Keynote"


def test_parser_accepts_uncertain_confidence() -> None:
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
    rows = parse_industry_events_text(payload)
    assert len(rows) == 1
    payload_dict = rows[0]["payload_json"]
    assert payload_dict is not None
    assert payload_dict["confidence"] == "uncertain"


# --- Registry sanity -----------------------------------------------------


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


def test_industry_event_response_rejects_non_http_source_url() -> None:
    """A malicious or hallucinated paste can't smuggle a ``javascript:``
    URL into ``source_url`` — the field validator blocks any scheme
    other than http(s) before the row reaches the DB."""
    import pydantic

    for bad in (
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "file:///etc/passwd",
        "ftp://example.com/",
    ):
        with pytest.raises(pydantic.ValidationError):
            IndustryEventResponse.model_validate(
                {
                    "registry_id": 1,
                    "name": "X",
                    "start_date": "2027-01-01",
                    "confidence": "confirmed",
                    "source_url": bad,
                }
            )

    # http(s) variants pass.
    for good in ("http://example.com", "https://example.com/path?q=1"):
        ok = IndustryEventResponse.model_validate(
            {
                "registry_id": 1,
                "name": "X",
                "start_date": "2027-01-01",
                "confidence": "confirmed",
                "source_url": good,
            }
        )
        assert ok.source_url == good


def test_parser_drops_entry_with_malicious_source_url() -> None:
    """Whole-batch behaviour: a poisoned entry is dropped, the good
    entries still get through. The bad row doesn't reach the upsert
    layer, so no Calendar Drawer link can ever point at a non-http URL."""
    payload = """[
      {
        "registry_id": 1,
        "name": "Good event",
        "start_date": "2027-03-15",
        "confidence": "confirmed",
        "source_url": "https://nvidia.com/gtc/"
      },
      {
        "registry_id": 9,
        "name": "Poisoned event",
        "start_date": "2026-06-08",
        "confidence": "confirmed",
        "source_url": "javascript:alert(1)"
      }
    ]"""
    rows = parse_industry_events_text(payload)
    assert len(rows) == 1
    assert rows[0]["title"] == "Good event"

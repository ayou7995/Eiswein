"""Calendar API — GET /calendar/events range + filter contract."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import CalendarEvent


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _seed(
    session_factory: sessionmaker[Session],
    rows: list[dict[str, object]],
) -> None:
    with session_factory() as session:
        for row in rows:
            session.add(CalendarEvent(**row))
        session.commit()


def test_calendar_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30")
    assert resp.status_code == 401


def test_calendar_empty_range_returns_zero(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    body = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30").json()
    assert body["total"] == 0
    assert body["data"] == []
    assert body["range_start"] == "2026-06-01"
    assert body["range_end"] == "2026-06-30"


def test_calendar_returns_events_in_range(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _seed(
        session_factory,
        [
            {
                "event_date": date(2026, 5, 30),  # outside
                "type": "earnings",
                "ticker_symbol": "AAPL",
                "title": "AAPL Earnings",
                "source": "yfinance",
            },
            {
                "event_date": date(2026, 6, 5),
                "type": "earnings",
                "ticker_symbol": "NVDA",
                "title": "NVDA Earnings",
                "event_time": "AMC",
                "payload_json": {"time_marker": "AMC"},
                "source": "yfinance",
            },
            {
                "event_date": date(2026, 6, 12),
                "type": "macro",
                "ticker_symbol": None,
                "title": "CPI Release",
                "event_time": "8:30 ET",
                "source": "hardcoded",
            },
        ],
    )
    _login(client, test_password)
    body = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30").json()
    assert body["total"] == 2
    titles = sorted(item["title"] for item in body["data"])
    assert titles == ["CPI Release", "NVDA Earnings"]


def test_calendar_filters_by_type(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _seed(
        session_factory,
        [
            {
                "event_date": date(2026, 6, 5),
                "type": "earnings",
                "ticker_symbol": "NVDA",
                "title": "NVDA Earnings",
                "source": "yfinance",
            },
            {
                "event_date": date(2026, 6, 12),
                "type": "macro",
                "ticker_symbol": None,
                "title": "CPI Release",
                "source": "hardcoded",
            },
        ],
    )
    _login(client, test_password)
    body = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30&types=macro").json()
    assert body["total"] == 1
    assert body["data"][0]["title"] == "CPI Release"


def test_calendar_ticker_filter_keeps_macro(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Filtering by ticker must NOT hide macro events — losing CPI
    when the user asked for 'just my EV tickers' is a UX trap."""
    _seed(
        session_factory,
        [
            {
                "event_date": date(2026, 6, 5),
                "type": "earnings",
                "ticker_symbol": "AAPL",
                "title": "AAPL Earnings",
                "source": "yfinance",
            },
            {
                "event_date": date(2026, 6, 6),
                "type": "earnings",
                "ticker_symbol": "NVDA",
                "title": "NVDA Earnings",
                "source": "yfinance",
            },
            {
                "event_date": date(2026, 6, 12),
                "type": "macro",
                "ticker_symbol": None,
                "title": "CPI Release",
                "source": "hardcoded",
            },
        ],
    )
    _login(client, test_password)
    body = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30&tickers=NVDA").json()
    titles = {item["title"] for item in body["data"]}
    assert "NVDA Earnings" in titles
    assert "CPI Release" in titles
    assert "AAPL Earnings" not in titles


def test_calendar_rejects_inverted_range(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/calendar/events?start=2026-07-01&end=2026-06-01")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_range"


def test_calendar_rejects_overly_wide_range(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/calendar/events?start=2024-01-01&end=2026-12-31")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "range_too_wide"


def test_calendar_response_carries_payload(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Earnings event payload (time_marker, consensus_eps) flows through
    to the wire so the frontend can render BMO/AMC chips."""
    _seed(
        session_factory,
        [
            {
                "event_date": date(2026, 6, 5),
                "type": "earnings",
                "ticker_symbol": "NVDA",
                "title": "NVDA Earnings",
                "event_time": "AMC",
                "payload_json": {"time_marker": "AMC", "consensus_eps": 0.78},
                "source": "yfinance",
            }
        ],
    )
    _login(client, test_password)
    body = client.get("/api/v1/calendar/events?start=2026-06-01&end=2026-06-30").json()
    item = body["data"][0]
    assert item["event_time"] == "AMC"
    assert item["payload"] == {"time_marker": "AMC", "consensus_eps": 0.78}
    assert item["source"] == "yfinance"


# --- Industry sync (manual paste flow) -----------------------------------


def test_industry_sync_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/calendar/industry-sync/status")
    assert resp.status_code == 401


def test_industry_sync_status_reports_no_sync_initially(
    client: TestClient, test_password: str
) -> None:
    """A fresh install has never imported — ``last_sync_at`` is null
    and the stale-days threshold is still surfaced for the UI."""
    _login(client, test_password)
    body = client.get("/api/v1/calendar/industry-sync/status").json()
    assert body["last_sync_at"] is None
    assert body["stale_days_threshold"] >= 7


def test_industry_sync_prompt_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/calendar/industry-sync/prompt")
    assert resp.status_code == 401


def test_industry_sync_prompt_includes_conference_registry(
    client: TestClient, test_password: str
) -> None:
    """The prompt must mention real conference names from the registry
    so a regression in ``build_industry_sync_prompt`` is caught here."""
    _login(client, test_password)
    body = client.get("/api/v1/calendar/industry-sync/prompt").json()
    assert "Computex" in body["prompt"]
    assert "NVIDIA GTC" in body["prompt"]
    assert "WWDC" in body["prompt"]
    assert "registry_id" in body["prompt"]
    # as_of is echoed back so the operator can sanity-check freshness.
    assert "as_of" in body


def test_industry_sync_import_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": "[]"},
    )
    assert resp.status_code == 401


def test_industry_sync_import_rejects_empty_body(client: TestClient, test_password: str) -> None:
    """Pydantic ``min_length=1`` rejects empty paste — the UI should
    never let it through, but we double-belt at the API."""
    _login(client, test_password)
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": ""},
    )
    assert resp.status_code == 422


def test_industry_sync_import_accepts_valid_paste(client: TestClient, test_password: str) -> None:
    """End-to-end paste: a real-shape JSON array round-trips through
    parsing + upsert and shows up in the calendar listing."""
    paste = (
        "[{"
        '"registry_id": 1,'
        '"name": "NVIDIA GTC 2027",'
        '"start_date": "2027-03-15",'
        '"end_date": "2027-03-19",'
        '"confidence": "confirmed",'
        '"source_url": "https://www.nvidia.com/gtc/",'
        '"notes": "Listed on the official GTC homepage."'
        "}]"
    )
    _login(client, test_password)
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": paste},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed_count"] == 1
    assert body["rows_upserted"] == 1

    # The status endpoint now reports a non-null last_sync_at.
    status = client.get("/api/v1/calendar/industry-sync/status").json()
    assert status["last_sync_at"] is not None

    # And the event is visible via the regular calendar list endpoint.
    listing = client.get("/api/v1/calendar/events?start=2027-03-01&end=2027-03-31").json()
    titles = [event["title"] for event in listing["data"]]
    assert "NVIDIA GTC 2027" in titles


def test_industry_sync_import_tolerates_markdown_fences(
    client: TestClient, test_password: str
) -> None:
    """Gemini occasionally wraps JSON in ```json fences despite the
    prompt; the parser strips them so the paste still imports."""
    paste = (
        "```json\n"
        "[{"
        '"registry_id": 1,'
        '"name": "NVIDIA GTC 2027",'
        '"start_date": "2027-03-15",'
        '"confidence": "confirmed"'
        "}]"
        "\n```"
    )
    _login(client, test_password)
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": paste},
    )
    assert resp.status_code == 200
    assert resp.json()["rows_upserted"] == 1


def test_industry_sync_import_partial_validation_keeps_good_rows(
    client: TestClient, test_password: str
) -> None:
    """One bad entry shouldn't tank the batch — per-entry validation
    drops the offender, good entries still flow through."""
    paste = (
        "["
        "{"  # good
        '"registry_id": 1,'
        '"name": "NVIDIA GTC 2027",'
        '"start_date": "2027-03-15",'
        '"confidence": "confirmed"'
        "},"
        "{"  # bad — missing start_date
        '"registry_id": 9,'
        '"name": "Apple WWDC 2026",'
        '"confidence": "estimated"'
        "}"
        "]"
    )
    _login(client, test_password)
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": paste},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed_count"] == 1
    assert body["rows_upserted"] == 1


def test_industry_sync_import_handles_garbage_paste_gracefully(
    client: TestClient, test_password: str
) -> None:
    """Garbage input → 200 with parsed_count=0 (not 4xx). The UI
    surfaces that as 'no events imported' so the operator knows to
    re-check the paste."""
    _login(client, test_password)
    resp = client.post(
        "/api/v1/calendar/industry-sync/import",
        json={"json_text": "definitely not JSON {[}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed_count"] == 0
    assert body["rows_upserted"] == 0

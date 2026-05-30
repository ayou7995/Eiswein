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


# --- Industry Gemini sync status + manual trigger -------------------------


def test_industry_sync_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/calendar/industry-sync/status")
    assert resp.status_code == 401


def test_industry_sync_status_reports_disabled_when_no_key(
    client: TestClient, test_password: str
) -> None:
    """Default settings fixture has no Gemini key — status reflects that."""
    _login(client, test_password)
    body = client.get("/api/v1/calendar/industry-sync/status").json()
    assert body["enabled"] is False
    assert body["last_sync_at"] is None
    assert body["stale_days_threshold"] >= 7


def test_industry_sync_run_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/calendar/industry-sync/run")
    assert resp.status_code == 401


def test_industry_sync_run_skips_gracefully_with_no_key(
    client: TestClient, test_password: str
) -> None:
    """Manual trigger without a configured Gemini key returns 200 with
    ``skipped_reason=no_api_key`` — no exception, just a clean signal
    the operator hasn't enabled this feature."""
    _login(client, test_password)
    resp = client.post("/api/v1/calendar/industry-sync/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_reason"] == "no_api_key"
    assert body["events_returned"] == 0
    assert body["rows_upserted"] == 0


def test_industry_sync_run_invokes_ingestion_when_key_set(
    client: TestClient,
    test_password: str,
    monkeypatch,
) -> None:
    """Happy path: inject a Gemini key into ``app.state.settings``, stub
    the LLM-bound ingestion entry, and verify the wire response carries
    the counts from the ingestion result.

    Settings is a pydantic ``BaseSettings`` and is frozen — we can't
    mutate the fixture in place, so we replace ``app.state.settings``
    with a copy carrying the key. ``get_settings_dep`` reads from
    app.state at request time so the next request picks it up
    automatically."""
    from pydantic import SecretStr

    real_app = client.app
    original_settings = real_app.state.settings
    real_app.state.settings = original_settings.model_copy(
        update={"gemini_api_key": SecretStr("fake-key")}
    )

    from app.api.v1 import calendar_routes
    from app.ingestion.industry_gemini_sync import IndustryGeminiSyncResult

    async def _fake_sync(session, *, api_key, as_of=None):
        return IndustryGeminiSyncResult(skipped_reason=None, events_returned=3, rows_upserted=3)

    monkeypatch.setattr(calendar_routes, "run_industry_gemini_sync", _fake_sync)

    try:
        _login(client, test_password)
        resp = client.post("/api/v1/calendar/industry-sync/run")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped_reason"] is None
        assert body["events_returned"] == 3
        assert body["rows_upserted"] == 3
    finally:
        real_app.state.settings = original_settings

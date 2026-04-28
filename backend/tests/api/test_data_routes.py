"""Data routes — status shape, refresh rate limit, only_status poll."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_data_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/data/status")
    assert resp.status_code == 401


def test_data_status_shape(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    resp = client.get("/api/v1/data/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "yfinance"
    assert body["provider_health"]["status"] in ("ok", "degraded", "error", "not_configured")
    assert "market_open_today" in body
    assert "last_trading_day" in body
    assert body["ticker_summary"]["ready"] + body["ticker_summary"]["pending"] >= 1


def test_data_refresh_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 401


def test_data_refresh_runs_job_and_returns_summary(
    client: TestClient, test_password: str, monkeypatch
) -> None:
    from app.ingestion import daily_ingestion

    monkeypatch.setattr(daily_ingestion, "is_trading_day_et", lambda: True)
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})

    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["market_open"] is True
    assert body["symbols_requested"] >= 1


def test_data_refresh_rate_limit(client: TestClient, test_password: str, monkeypatch) -> None:
    from app.ingestion import daily_ingestion

    monkeypatch.setattr(daily_ingestion, "is_trading_day_et", lambda: True)
    _login(client, test_password)
    for i in range(5):
        resp = client.post("/api/v1/data/refresh")
        assert resp.status_code == 200, f"call #{i + 1} unexpectedly rejected"
    sixth = client.post("/api/v1/data/refresh")
    assert sixth.status_code == 429
    assert sixth.json()["error"]["code"] == "rate_limited"


def test_ticker_only_status_returns_light_payload(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    resp = client.get("/api/v1/ticker/SPY?only_status=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SPY"
    assert "data_status" in body
    # last_refresh_at is present even if null.
    assert "last_refresh_at" in body


def test_ticker_unknown_returns_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/NOPE?only_status=1")
    assert resp.status_code == 404


def test_ticker_rejects_invalid_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/bad symbol?only_status=1")
    assert resp.status_code == 422

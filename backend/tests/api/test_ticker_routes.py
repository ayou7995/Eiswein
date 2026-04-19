"""Ticker indicators endpoint tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.daily_signal_repository import (
    DailySignalRepository,
    result_to_row,
)
from app.indicators.base import IndicatorResult, SignalTone


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_ticker_indicators_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/ticker/SPY/indicators")
    assert resp.status_code == 401


def test_ticker_indicators_returns_stored_rows(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "AAPL"})

    # Inject a computed indicator row directly (bypass daily_update).
    with session_factory() as session:
        repo = DailySignalRepository(session)
        today = date(2024, 12, 31)
        result = IndicatorResult(
            name="rsi",
            value=55.0,
            signal=SignalTone.YELLOW,  # type: ignore[arg-type]
            data_sufficient=True,
            short_label="RSI 中性 55",
            detail={"daily_rsi": 55.0, "weekly_rsi": 50.0},
            computed_at=datetime.now(UTC),
        )
        repo.upsert_many([result_to_row("AAPL", today, result)])
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicators")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["date"] == "2024-12-31"
    assert body["indicator_version"]
    assert "rsi" in body["indicators"]
    assert body["indicators"]["rsi"]["signal"] == "yellow"
    assert body["indicators"]["rsi"]["short_label"] == "RSI 中性 55"


def test_ticker_indicators_not_on_watchlist_is_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/TSLA/indicators")
    assert resp.status_code == 404


def test_ticker_indicators_no_computed_rows_is_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    # Add to watchlist but never compute indicators.
    client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    resp = client.get("/api/v1/ticker/AAPL/indicators")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_ticker_indicators_rejects_invalid_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/bad symbol/indicators")
    assert resp.status_code == 422

"""Ticker composed signal endpoint tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.daily_signal_repository import (
    DailySignalRepository,
    result_to_row,
)
from app.db.repositories.ticker_snapshot_repository import (
    TickerSnapshotRepository,
    composed_to_row,
)
from app.indicators.base import IndicatorResult, SignalTone
from app.signals.compose import compose_signal
from app.signals.types import (
    ActionCategory,
    EntryTiers,
    MarketPosture,
    TimingModifier,
)


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _seed_snapshot(
    session: Session,
    *,
    symbol: str,
    trade_date: date,
    action: ActionCategory = ActionCategory.STRONG_BUY,
    timing: TimingModifier = TimingModifier.FAVORABLE,
) -> None:
    composed = compose_signal(
        symbol=symbol,
        trade_date=trade_date,
        action=action,
        direction_green_count=4,
        direction_red_count=0,
        timing_modifier=timing,
        market_posture=MarketPosture.OFFENSIVE,
        entry_tiers=EntryTiers(
            aggressive=Decimal("150.0000"),
            ideal=Decimal("148.0000"),
            conservative=Decimal("140.0000"),
        ),
        stop_loss=Decimal("135.8000"),
        computed_at=datetime.now(UTC),
    )
    TickerSnapshotRepository(session).upsert_many([composed_to_row(composed)])


def _seed_indicator_rows(session: Session, *, symbol: str, trade_date: date) -> None:
    repo = DailySignalRepository(session)
    rows = []
    for name in ("price_vs_ma", "rsi", "macd"):
        rows.append(
            result_to_row(
                symbol,
                trade_date,
                IndicatorResult(
                    name=name,
                    value=1.0,
                    signal=SignalTone.GREEN,  # type: ignore[arg-type]
                    data_sufficient=True,
                    short_label=f"{name} 測試",
                    detail={},
                    computed_at=datetime.now(UTC),
                ),
            )
        )
    repo.upsert_many(rows)


def test_ticker_signal_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/ticker/SPY/signal")
    assert resp.status_code == 401


def test_ticker_signal_returns_404_when_not_on_watchlist(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/TSLA/signal")
    assert resp.status_code == 404


def test_ticker_signal_returns_404_when_no_snapshot(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    resp = client.get("/api/v1/ticker/AAPL/signal")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_ticker_signal_returns_composed_response(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    today = date(2024, 12, 31)

    with session_factory() as session:
        _seed_snapshot(session, symbol="AAPL", trade_date=today)
        _seed_indicator_rows(session, symbol="AAPL", trade_date=today)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/signal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["action"] == "strong_buy"
    assert body["action_label"].startswith("強力買入")
    assert body["timing_modifier"] == "favorable"
    assert body["timing_badge"] == "✓ 時機好"
    assert body["show_timing_modifier"] is True
    assert body["market_posture_at_compute"] == "offensive"
    assert body["entry_tiers"]["aggressive"] == "150.0000"
    assert body["stop_loss"] == "135.8000"
    # Pros/cons assembled from stored indicator rows.
    names = {i["indicator_name"] for i in body["pros_cons"]}
    assert {"price_vs_ma", "rsi", "macd"} <= names


def test_ticker_signal_suppresses_timing_badge_for_exit_action(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    today = date(2024, 12, 31)
    with session_factory() as session:
        _seed_snapshot(
            session,
            symbol="AAPL",
            trade_date=today,
            action=ActionCategory.EXIT,
            timing=TimingModifier.FAVORABLE,
        )
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/signal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "exit"
    # D1b: no timing badge when show_timing_modifier=False.
    assert body["show_timing_modifier"] is False
    assert body["timing_badge"] is None


def test_ticker_signal_rejects_invalid_symbol(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/bad symbol/signal")
    assert resp.status_code == 422

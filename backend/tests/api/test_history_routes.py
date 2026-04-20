"""History API — posture timeline, signal accuracy, decision history."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    DailyPrice,
    MarketSnapshot,
    TickerSnapshot,
    Trade,
    User,
    Watchlist,
)


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_history_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/history/market-posture").status_code == 401
    assert client.get("/api/v1/history/signal-accuracy?symbol=SPY").status_code == 401
    assert client.get("/api/v1/history/decisions").status_code == 401


def test_market_posture_history_empty(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/history/market-posture?days=7")
    assert resp.status_code == 200
    assert resp.json() == {"data": [], "total": 0, "has_more": False}


def test_market_posture_history_returns_timeline(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        for day, posture in enumerate(["normal", "offensive", "defensive"], start=1):
            session.add(
                MarketSnapshot(
                    date=date(2026, 4, day),
                    posture=posture,
                    regime_green_count=1,
                    regime_red_count=1,
                    regime_yellow_count=2,
                    indicator_version="v1",
                    computed_at=datetime(2026, 4, day, tzinfo=UTC),
                )
            )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/history/market-posture?days=365").json()
    assert body["total"] == 3
    # Ordered ascending by date.
    assert [r["posture"] for r in body["data"]] == ["normal", "offensive", "defensive"]


def test_signal_accuracy_requires_watchlist(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/history/signal-accuracy?symbol=NOPE")
    assert resp.status_code == 404


def test_signal_accuracy_math(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Known fixture: 2 BUY signals on days 1 and 10.

    * Day 1 close=100; day 6 close=110 → BUY correct (up).
    * Day 10 close=120; day 15 close=115 → BUY incorrect (down).
    Accuracy should be 50%.
    """
    with session_factory() as session:
        admin = session.execute(
            __import__("sqlalchemy").select(User).where(User.username == "admin")
        ).scalar_one()
        session.add(Watchlist(user_id=admin.id, symbol="SPY", data_status="ready"))
        for d, close in [
            (1, 100),
            (6, 110),
            (10, 120),
            (15, 115),
        ]:
            session.add(
                DailyPrice(
                    symbol="SPY",
                    date=date(2026, 1, d),
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=1,
                )
            )
        for d in (1, 10):
            session.add(
                TickerSnapshot(
                    symbol="SPY",
                    date=date(2026, 1, d),
                    action="buy",
                    direction_green_count=3,
                    direction_red_count=0,
                    timing_modifier="good",
                    show_timing_modifier=True,
                    entry_aggressive=None,
                    entry_ideal=None,
                    entry_conservative=None,
                    stop_loss=None,
                    market_posture_at_compute="normal",
                    indicator_version="v1",
                    computed_at=datetime(2026, 1, d, tzinfo=UTC),
                )
            )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/history/signal-accuracy?symbol=SPY&horizon=5").json()
    assert body["total_signals"] == 2
    assert body["correct"] == 1
    assert body["accuracy_pct"] == 50.0
    assert body["by_action"]["buy"]["accuracy_pct"] == 50.0


def test_signal_accuracy_skips_signals_without_forward_data(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """A snapshot on the most recent day has no forward data — it
    must be skipped (not counted as correct or incorrect)."""
    with session_factory() as session:
        admin = session.execute(
            __import__("sqlalchemy").select(User).where(User.username == "admin")
        ).scalar_one()
        session.add(Watchlist(user_id=admin.id, symbol="SPY", data_status="ready"))
        # Only one price row — no forward horizon available.
        session.add(
            DailyPrice(
                symbol="SPY",
                date=date(2026, 1, 10),
                open=Decimal(100),
                high=Decimal(100),
                low=Decimal(100),
                close=Decimal(100),
                volume=1,
            )
        )
        session.add(
            TickerSnapshot(
                symbol="SPY",
                date=date(2026, 1, 10),
                action="buy",
                direction_green_count=3,
                direction_red_count=0,
                timing_modifier="good",
                show_timing_modifier=True,
                entry_aggressive=None,
                entry_ideal=None,
                entry_conservative=None,
                stop_loss=None,
                market_posture_at_compute="normal",
                indicator_version="v1",
                computed_at=datetime(2026, 1, 10, tzinfo=UTC),
            )
        )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/history/signal-accuracy?symbol=SPY&horizon=5").json()
    assert body["total_signals"] == 0


def test_decisions_history_matches_snapshot(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        admin = session.execute(
            __import__("sqlalchemy").select(User).where(User.username == "admin")
        ).scalar_one()
        session.add(
            TickerSnapshot(
                symbol="SPY",
                date=date(2026, 1, 2),
                action="buy",
                direction_green_count=3,
                direction_red_count=0,
                timing_modifier="good",
                show_timing_modifier=True,
                entry_aggressive=None,
                entry_ideal=None,
                entry_conservative=None,
                stop_loss=None,
                market_posture_at_compute="normal",
                indicator_version="v1",
                computed_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
        session.add(
            Trade(
                user_id=admin.id,
                position_id=None,
                symbol="SPY",
                side="buy",
                shares=Decimal("1"),
                price=Decimal("100"),
                executed_at=datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
            )
        )
        session.commit()

    _login(client, test_password)
    body = client.get("/api/v1/history/decisions?limit=30").json()
    assert body["total"] == 1
    item = body["data"][0]
    assert item["symbol"] == "SPY"
    assert item["eiswein_action"] == "buy"
    assert item["matched_recommendation"] is True


def test_decisions_history_user_isolation(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    admin_password_hash: str,
) -> None:
    """Another user's trades must never appear in caller's history."""
    with session_factory() as session:
        bob = User(username="bob", password_hash=admin_password_hash, is_active=True)
        session.add(bob)
        session.flush()
        session.add(
            Trade(
                user_id=bob.id,
                position_id=None,
                symbol="TSLA",
                side="buy",
                shares=Decimal("1"),
                price=Decimal("200"),
                executed_at=datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
            )
        )
        session.commit()

    _login(client, test_password)  # as admin
    body = client.get("/api/v1/history/decisions").json()
    assert body["total"] == 0

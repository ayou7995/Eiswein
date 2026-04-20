"""Market posture endpoint tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.daily_signal_repository import (
    DailySignalRepository,
    result_to_row,
)
from app.db.repositories.market_posture_streak_repository import (
    MarketPostureStreakRepository,
)
from app.db.repositories.market_snapshot_repository import (
    MarketSnapshotRepository,
    build_market_snapshot_row,
)
from app.indicators.base import IndicatorResult, SignalTone
from app.signals.types import MarketPosture


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_market_posture_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/market-posture")
    assert resp.status_code == 401


def test_market_posture_returns_404_when_no_snapshot(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/market-posture")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_market_posture_returns_latest_snapshot(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    today = date(2024, 12, 31)

    with session_factory() as session:
        MarketSnapshotRepository(session).upsert(
            build_market_snapshot_row(
                trade_date=today,
                posture=MarketPosture.OFFENSIVE,
                regime_green_count=3,
                regime_red_count=0,
                regime_yellow_count=1,
                indicator_version="1.0.0",
                computed_at=datetime.now(UTC),
            )
        )
        MarketPostureStreakRepository(session).record_posture(
            as_of_date=today,
            posture=MarketPosture.OFFENSIVE,
            computed_at=datetime.now(UTC),
        )
        # Seed one regime indicator for the pros_cons list.
        sig_repo = DailySignalRepository(session)
        result = IndicatorResult(
            name="spx_ma",
            value=5000.0,
            signal=SignalTone.GREEN,  # type: ignore[arg-type]
            data_sufficient=True,
            short_label="SPX 多頭排列",
            detail={"price": 5000.0, "ma50": 4900.0, "ma200": 4800.0},
            computed_at=datetime.now(UTC),
        )
        sig_repo.upsert_many([result_to_row("SPY", today, result)])
        session.commit()

    resp = client.get("/api/v1/market-posture")
    assert resp.status_code == 200
    body = resp.json()
    assert body["posture"] == "offensive"
    assert body["posture_label"] == "進攻"
    assert body["regime_green_count"] == 3
    assert body["streak_days"] == 1
    # Streak < 3 → no badge.
    assert body["streak_badge"] is None
    # pros_cons has the seeded spx_ma entry with tone="pro".
    names = [i["indicator_name"] for i in body["pros_cons"]]
    assert "spx_ma" in names
    spx_item = next(i for i in body["pros_cons"] if i["indicator_name"] == "spx_ma")
    assert spx_item["tone"] == "pro"
    assert spx_item["category"] == "macro"


def test_market_posture_streak_badge_emitted_at_3_days(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    target = date(2024, 12, 31)

    with session_factory() as session:
        streak_repo = MarketPostureStreakRepository(session)
        for d in (date(2024, 12, 27), date(2024, 12, 30), target):
            streak_repo.record_posture(
                as_of_date=d,
                posture=MarketPosture.OFFENSIVE,
                computed_at=datetime.now(UTC),
            )
        MarketSnapshotRepository(session).upsert(
            build_market_snapshot_row(
                trade_date=target,
                posture=MarketPosture.OFFENSIVE,
                regime_green_count=3,
                regime_red_count=0,
                regime_yellow_count=1,
                indicator_version="1.0.0",
                computed_at=datetime.now(UTC),
            )
        )
        session.commit()

    resp = client.get("/api/v1/market-posture")
    assert resp.status_code == 200
    body = resp.json()
    assert body["streak_days"] == 3
    assert body["streak_badge"] is not None
    assert "進攻" in body["streak_badge"]

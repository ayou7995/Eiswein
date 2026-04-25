"""Indicator drift + revalidate endpoints — /api/v1/indicators/*."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import BackfillJob, TickerSnapshot
from app.indicators.base import INDICATOR_VERSION


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _make_ticker_snapshot_row(
    *,
    symbol: str,
    trade_date: date,
    version: str,
) -> TickerSnapshot:
    return TickerSnapshot(
        symbol=symbol,
        date=trade_date,
        action="hold",
        direction_green_count=0,
        direction_red_count=0,
        timing_modifier="none",
        show_timing_modifier=False,
        market_posture_at_compute="normal",
        indicator_version=version,
        computed_at=datetime.now(UTC),
    )


# --- Drift ---------------------------------------------------------------


def test_drift_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/indicators/drift")
    assert resp.status_code == 401


def test_drift_no_rows_has_no_drift(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/indicators/drift")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_drift"] is False
    assert body["current_version"] == INDICATOR_VERSION
    assert body["stale_versions"] == []
    assert body["stale_row_count"] == 0
    assert body["running_revalidation_job_id"] is None


def test_drift_detects_stale_rows(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        session.add_all(
            [
                _make_ticker_snapshot_row(
                    symbol="SPY", trade_date=date(2026, 4, 1), version="v0.old"
                ),
                _make_ticker_snapshot_row(
                    symbol="SPY", trade_date=date(2026, 4, 2), version="v0.old"
                ),
                _make_ticker_snapshot_row(
                    symbol="SPY", trade_date=date(2026, 4, 3), version=INDICATOR_VERSION
                ),
            ]
        )
        session.commit()

    body = client.get("/api/v1/indicators/drift").json()
    assert body["has_drift"] is True
    assert body["stale_versions"] == ["v0.old"]
    assert body["stale_row_count"] == 2
    assert body["running_revalidation_job_id"] is None


def test_drift_reports_running_revalidation_job(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        session.add(
            _make_ticker_snapshot_row(symbol="SPY", trade_date=date(2026, 4, 1), version="v0.old")
        )
        job = BackfillJob(
            kind="revalidation",
            symbol=None,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 22),
            state="running",
            force=True,
            created_by_user_id=1,
            started_at=datetime.now(UTC),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    body = client.get("/api/v1/indicators/drift").json()
    assert body["running_revalidation_job_id"] == job_id


# --- Revalidate ----------------------------------------------------------


def test_revalidate_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/indicators/revalidate", json={})
    assert resp.status_code == 401


def test_revalidate_returns_201_with_job_id(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/indicators/revalidate", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["job_id"], int)


def test_revalidate_409_when_job_running(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        session.add(
            BackfillJob(
                kind="revalidation",
                symbol=None,
                from_date=date(2026, 4, 1),
                to_date=date(2026, 4, 2),
                state="running",
                force=True,
                created_by_user_id=1,
            )
        )
        session.commit()

    resp = client.post("/api/v1/indicators/revalidate", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "backfill_already_running"

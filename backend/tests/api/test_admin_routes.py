"""Generic job polling + cancel endpoints — /api/v1/jobs/*.

Post Phase-1 UX overhaul there is no plan/start surface: onboarding is
driven by the watchlist route and revalidation by the indicators route.
The only public surface here is the generic "look up a job row" +
"cancel a running job" pair used by both flows.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import BackfillJob


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


# --- Auth -----------------------------------------------------------------


def test_get_job_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs/1")
    assert resp.status_code == 401


def test_cancel_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs/1/cancel")
    assert resp.status_code == 401


# --- Get job --------------------------------------------------------------


def test_get_job_returns_full_row(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        row = BackfillJob(
            kind="revalidation",
            symbol=None,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 2),
            state="completed",
            force=True,
            processed_days=2,
            total_days=2,
            created_by_user_id=1,
        )
        session.add(row)
        session.commit()
        job_id = row.id

    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["id"] == job_id
    assert body["kind"] == "revalidation"
    assert body["symbol"] is None
    assert body["state"] == "completed"
    assert body["force"] is True
    assert body["processed_days"] == 2


def test_get_onboarding_job_surfaces_symbol(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        row = BackfillJob(
            kind="onboarding",
            symbol="NVDA",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            state="running",
            force=False,
            created_by_user_id=1,
        )
        session.add(row)
        session.commit()
        job_id = row.id

    body = client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["kind"] == "onboarding"
    assert body["symbol"] == "NVDA"


def test_get_job_404_when_missing(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/jobs/999999")
    assert resp.status_code == 404


# --- Cancel ---------------------------------------------------------------


def test_cancel_sets_flag_and_returns_202(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        row = BackfillJob(
            kind="revalidation",
            symbol=None,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 2),
            state="running",
            force=True,
            created_by_user_id=1,
        )
        session.add(row)
        session.commit()
        job_id = row.id

    resp = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 202
    body = resp.json()
    assert body["cancel_requested"] is True


def test_cancel_idempotent_on_terminal_job(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        row = BackfillJob(
            kind="revalidation",
            symbol=None,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 2),
            state="completed",
            force=True,
            created_by_user_id=1,
        )
        session.add(row)
        session.commit()
        job_id = row.id

    resp = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert resp.status_code == 202
    body = resp.json()
    # Terminal state preserved, cancel_requested NOT flipped.
    assert body["state"] == "completed"
    assert body["cancel_requested"] is False


def test_cancel_404_when_missing(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/jobs/999999/cancel")
    assert resp.status_code == 404

"""Watchlist API — pessimistic validation + async onboarding + SPY protection.

Phase 1 UX overhaul: POST /watchlist is always 201 with a job_id.
There is no sync/async fork — all onboarding is async, tracked by a
BackfillJob row. Tests drive the in-process runner inline (see
``onboarding_run_inline=True`` in conftest) so job state has settled
before the response is checked.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_watchlist_list_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 401


def test_watchlist_add_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    assert resp.status_code == 401


def test_watchlist_add_returns_201_with_job_id(client: TestClient, test_password: str) -> None:
    """Happy path: valid ticker → 201 with job_id, row ends up ready."""
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["symbol"] == "NVDA"
    # Onboarding ran inline — ``ready`` after thread finishes.
    assert body["data"]["data_status"] == "ready"
    assert "job_id" in body and isinstance(body["job_id"], int)
    assert body["job_id"] > 0


def test_watchlist_list_returns_paginated_wrapper(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    client.post("/api/v1/watchlist", json={"symbol": "QQQ"})
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["has_more"] is False
    symbols = {item["symbol"] for item in body["data"]}
    assert symbols == {"NVDA", "QQQ"}


def test_watchlist_add_rejects_invalid_format(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "bad symbol"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_watchlist_add_rejects_too_long_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "ABCDEFGHIJK"})
    assert resp.status_code == 422


def test_watchlist_add_invalid_ticker_returns_400(
    client: TestClient, test_password: str, app
) -> None:
    """Empty frame from pre-flight → 400 invalid_ticker, no row created."""
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    ds = FakeDataSource(FakeDataSourceConfig(empty_for={"ZZZZ"}))
    app.state.data_source = ds

    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "ZZZZ"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_ticker"

    # No watchlist row persisted — the pre-flight short-circuits.
    listing = client.get("/api/v1/watchlist").json()
    assert listing["total"] == 0


def test_watchlist_add_duplicate_returns_409(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    first = client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    assert first.status_code == 201
    second = client.post("/api/v1/watchlist", json={"symbol": "nvda"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "watchlist_duplicate"


def test_watchlist_add_over_cap_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    # Settings fixture sets max_size=5.
    for sym in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        resp = client.post("/api/v1/watchlist", json={"symbol": sym})
        assert resp.status_code == 201
    resp = client.post("/api/v1/watchlist", json={"symbol": "FFF"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "watchlist_full"


def test_watchlist_add_preflight_network_error_returns_503(
    client: TestClient, test_password: str, app
) -> None:
    """DataSourceError during pre-flight → 503 preflight_unavailable."""
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    ds = FakeDataSource(FakeDataSourceConfig(error_for={"NVDA"}))
    app.state.data_source = ds

    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "preflight_unavailable"


def test_watchlist_delete_requires_auth(client: TestClient) -> None:
    resp = client.delete("/api/v1/watchlist/NVDA")
    assert resp.status_code == 401


def test_watchlist_delete_returns_404_for_unknown_symbol(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/NOPE")
    assert resp.status_code == 404


def test_watchlist_delete_removes_row(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    resp = client.delete("/api/v1/watchlist/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    listing = client.get("/api/v1/watchlist").json()
    assert listing["total"] == 0


def test_watchlist_delete_validates_symbol_shape(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/bad symbol")
    assert resp.status_code == 422


def test_watchlist_delete_spy_returns_403(client: TestClient, test_password: str) -> None:
    """SPY is the system benchmark — user cannot remove it.

    First we add SPY (SPY is a valid symbol so the pre-flight passes
    with the default FakeDataSource), then DELETE must come back 403
    with code spy_is_system.
    """
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    resp = client.delete("/api/v1/watchlist/SPY")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "spy_is_system"


def test_watchlist_delete_cancels_active_onboarding(
    client: TestClient,
    test_password: str,
    session_factory,
    app,
) -> None:
    """DELETE on a pending row flips the onboarding job's cancel flag.

    We simulate "still pending" by manually setting the row back to
    ``pending`` after the inline onboarding completes, then inserting
    a fresh active onboarding BackfillJob. This avoids the
    infrastructure around racing threads which would be flaky in-process.
    """
    from datetime import UTC, date, datetime

    from app.db.models import BackfillJob, Watchlist

    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})

    with session_factory() as session:
        row = session.query(Watchlist).filter_by(symbol="NVDA").one()
        row.data_status = "pending"
        today = date(2026, 4, 24)
        job = BackfillJob(
            kind="onboarding",
            symbol="NVDA",
            from_date=today,
            to_date=today,
            state="running",
            force=False,
            created_by_user_id=row.user_id,
            started_at=datetime.now(UTC),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    resp = client.delete("/api/v1/watchlist/NVDA")
    assert resp.status_code == 200

    with session_factory() as session:
        refreshed = session.get(BackfillJob, job_id)
        assert refreshed is not None
        assert refreshed.cancel_requested is True

        # Watchlist row is gone.
        wl = session.query(Watchlist).filter_by(symbol="NVDA").one_or_none()
        assert wl is None


def test_watchlist_list_includes_active_onboarding_job_id(
    client: TestClient,
    test_password: str,
    session_factory,
) -> None:
    """Pending rows carry their active onboarding job_id for UI linking."""
    from datetime import UTC, date, datetime

    from app.db.models import BackfillJob, Watchlist

    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})

    with session_factory() as session:
        row = session.query(Watchlist).filter_by(symbol="NVDA").one()
        row.data_status = "pending"
        today = date(2026, 4, 24)
        job = BackfillJob(
            kind="onboarding",
            symbol="NVDA",
            from_date=today,
            to_date=today,
            state="running",
            force=False,
            created_by_user_id=row.user_id,
            started_at=datetime.now(UTC),
        )
        session.add(job)
        session.commit()
        expected_job_id = job.id

    listing = client.get("/api/v1/watchlist").json()
    [item] = [i for i in listing["data"] if i["symbol"] == "NVDA"]
    assert item["data_status"] == "pending"
    assert item["active_onboarding_job_id"] == expected_job_id

"""Watchlist API — auth, cold-start, validation, duplicates, cap."""

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


def test_watchlist_add_returns_ready_on_success(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["symbol"] == "SPY"
    assert body["data"]["data_status"] == "ready"
    assert body["data"]["last_refresh_at"] is not None


def test_watchlist_list_returns_paginated_wrapper(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    client.post("/api/v1/watchlist", json={"symbol": "QQQ"})
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["has_more"] is False
    symbols = {item["symbol"] for item in body["data"]}
    assert symbols == {"SPY", "QQQ"}


def test_watchlist_add_rejects_invalid_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "bad symbol"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_watchlist_add_rejects_too_long_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "ABCDEFGHIJK"})
    assert resp.status_code == 422


def test_watchlist_add_duplicate_returns_409(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    first = client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    assert first.status_code == 200
    second = client.post("/api/v1/watchlist", json={"symbol": "spy"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "watchlist_duplicate"


def test_watchlist_add_over_cap_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    # Settings fixture sets max_size=5.
    for sym in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        resp = client.post("/api/v1/watchlist", json={"symbol": sym})
        assert resp.status_code == 200
    resp = client.post("/api/v1/watchlist", json={"symbol": "FFF"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "watchlist_full"


def test_watchlist_add_cold_start_timeout_returns_202(
    client: TestClient, test_password: str, app
) -> None:
    """When backfill exceeds the 5s budget, route returns 202 with pending.

    We shrink the budget to 0.05s and set the fake source to delay 0.2s,
    so the timeout fires. The background task still completes in <1s.
    """
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    slow = FakeDataSource(FakeDataSourceConfig(delay_seconds=0.2))
    app.state.data_source = slow

    _login(client, test_password)
    import app.api.v1.watchlist_routes as wr

    original = wr._COLD_START_BUDGET_SECONDS
    wr._COLD_START_BUDGET_SECONDS = 0.05
    try:
        resp = client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    finally:
        wr._COLD_START_BUDGET_SECONDS = original
    assert resp.status_code == 202
    assert resp.json()["data"]["data_status"] == "pending"


def test_watchlist_add_handles_delisted_data(client: TestClient, test_password: str, app) -> None:
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    ds = FakeDataSource(FakeDataSourceConfig(empty_for={"ZZZZ"}))
    app.state.data_source = ds

    _login(client, test_password)
    resp = client.post("/api/v1/watchlist", json={"symbol": "ZZZZ"})
    # The row is created; data_status=delisted after DataSourceError.
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["symbol"] == "ZZZZ"
    assert body["data"]["data_status"] == "delisted"


def test_watchlist_delete_requires_auth(client: TestClient) -> None:
    resp = client.delete("/api/v1/watchlist/SPY")
    assert resp.status_code == 401


def test_watchlist_delete_returns_404_for_unknown_symbol(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/NOPE")
    assert resp.status_code == 404


def test_watchlist_delete_removes_row(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    resp = client.delete("/api/v1/watchlist/SPY")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    listing = client.get("/api/v1/watchlist").json()
    assert listing["total"] == 0


def test_watchlist_delete_validates_symbol_shape(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/bad symbol")
    assert resp.status_code == 422

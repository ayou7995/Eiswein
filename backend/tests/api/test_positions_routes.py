"""Positions API — CRUD, weighted avg cost, realized P&L, auth isolation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import User


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _add_watchlist(client: TestClient, symbol: str) -> None:
    resp = client.post("/api/v1/watchlist", json={"symbol": symbol})
    # Phase 1 UX overhaul: watchlist POST is always 201 (async onboarding).
    assert resp.status_code == 201, resp.text


def _open_payload(symbol: str = "SPY", shares: str = "10", price: str = "100") -> dict:
    return {
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "executed_at": datetime(2026, 1, 2, 15, 0, tzinfo=UTC).isoformat(),
        "note": "test",
    }


def _adjust_payload(shares: str, price: str) -> dict:
    return {
        "shares": shares,
        "price": price,
        "executed_at": datetime(2026, 1, 3, 15, 0, tzinfo=UTC).isoformat(),
    }


def test_positions_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/positions").status_code == 401
    assert client.post("/api/v1/positions", json=_open_payload()).status_code == 401


def test_open_requires_watchlisted_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/positions", json=_open_payload())
    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["reason"] == "symbol_not_on_watchlist"


def test_open_and_list(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    resp = client.post("/api/v1/positions", json=_open_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["symbol"] == "SPY"
    assert body["data"]["shares"] == "10.000000"
    assert body["data"]["avg_cost"] == "100.000000"
    assert body["data"]["closed_at"] is None

    # The list endpoint shows open positions only by default.
    listing = client.get("/api/v1/positions").json()
    assert listing["total"] == 1
    # current_price is derived from DailyPrice — fake source populated
    # it via backfill; unrealized_pnl should be present.
    assert listing["data"][0]["current_price"] is not None


def test_open_duplicate_returns_409(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    client.post("/api/v1/positions", json=_open_payload())
    second = client.post("/api/v1/positions", json=_open_payload())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "position_open_exists"


def test_open_rejects_zero_shares(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    payload = _open_payload(shares="0")
    resp = client.post("/api/v1/positions", json=payload)
    assert resp.status_code == 422


def test_add_weighted_average_math(client: TestClient, test_password: str) -> None:
    """Three successive /add calls — verify weighted-average cost math."""
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="10", price="100")).json()
    pid = opened["data"]["id"]

    # +5 @ 120 => 15 @ (10*100 + 5*120)/15 = 1600/15 = 106.666...
    resp1 = client.post(f"/api/v1/positions/{pid}/add", json=_adjust_payload("5", "120"))
    assert resp1.status_code == 200
    body1 = resp1.json()["data"]
    assert body1["shares"] == "15.000000"
    expected_cost_1 = (Decimal("1000") + Decimal("600")) / Decimal("15")
    assert Decimal(body1["avg_cost"]) == expected_cost_1.quantize(Decimal("0.000001"))

    # +5 @ 80
    resp2 = client.post(f"/api/v1/positions/{pid}/add", json=_adjust_payload("5", "80"))
    body2 = resp2.json()["data"]
    expected_cost_2 = (Decimal("15") * expected_cost_1 + Decimal("5") * Decimal("80")) / Decimal(
        "20"
    )
    assert Decimal(body2["avg_cost"]) == expected_cost_2.quantize(Decimal("0.000001"))
    assert body2["shares"] == "20.000000"

    # +10 @ 60
    resp3 = client.post(f"/api/v1/positions/{pid}/add", json=_adjust_payload("10", "60"))
    body3 = resp3.json()["data"]
    expected_cost_3 = (Decimal("20") * expected_cost_2 + Decimal("10") * Decimal("60")) / Decimal(
        "30"
    )
    assert Decimal(body3["avg_cost"]) == expected_cost_3.quantize(Decimal("0.000001"))


def test_reduce_computes_realized_pnl(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="10", price="100")).json()
    pid = opened["data"]["id"]

    resp = client.post(f"/api/v1/positions/{pid}/reduce", json=_adjust_payload("4", "120"))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["shares"] == "6.000000"
    # avg_cost preserved on partial sell
    assert body["avg_cost"] == "100.000000"
    assert body["closed_at"] is None

    detail = client.get(f"/api/v1/positions/{pid}").json()["data"]
    trades = detail["recent_trades"]
    sell = next(t for t in trades if t["side"] == "sell")
    # Realized P&L was computed server-side, NOT client-supplied:
    # (120 - 100) * 4 = 80
    assert sell["realized_pnl"] == "80.000000"


def test_reduce_full_auto_closes(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="3", price="100")).json()
    pid = opened["data"]["id"]
    resp = client.post(f"/api/v1/positions/{pid}/reduce", json=_adjust_payload("3", "150"))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["shares"] == "0.000000"
    assert body["closed_at"] is not None


def test_reduce_rejects_over_reduce(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="2", price="100")).json()
    pid = opened["data"]["id"]
    resp = client.post(f"/api/v1/positions/{pid}/reduce", json=_adjust_payload("3", "110"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_shares"


def test_delete_refuses_when_shares_remain(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="1", price="100")).json()
    pid = opened["data"]["id"]
    resp = client.delete(f"/api/v1/positions/{pid}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "has_remaining_shares"


def test_delete_succeeds_after_full_reduce(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="1", price="100")).json()
    pid = opened["data"]["id"]
    client.post(f"/api/v1/positions/{pid}/reduce", json=_adjust_payload("1", "110"))
    resp = client.delete(f"/api/v1/positions/{pid}")
    # Already auto-closed by the reduce; close_if_empty is a no-op.
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_get_position_returns_404_for_missing(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/positions/999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "position_not_found"


def test_cannot_access_other_users_position(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
    admin_password_hash: str,
) -> None:
    """Cross-user isolation: alice opens a position, admin cannot touch it."""
    # Create a second user "alice" directly in the DB + assign her a
    # watchlist row + position. Then log in as admin and verify every
    # per-id endpoint returns 404 (never 200 with another user's data,
    # never 403 — we want 404 so the id's existence isn't leaked).
    from decimal import Decimal

    from app.db.models import Position, Watchlist

    with session_factory() as session:
        alice = User(
            username="alice",
            password_hash=admin_password_hash,
            is_active=True,
        )
        session.add(alice)
        session.flush()
        session.add(Watchlist(user_id=alice.id, symbol="SPY", data_status="ready"))
        session.flush()
        p = Position(
            user_id=alice.id,
            symbol="SPY",
            shares=Decimal("1"),
            avg_cost=Decimal("100"),
            opened_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        session.add(p)
        session.flush()
        alice_pos_id = p.id
        session.commit()

    _login(client, test_password)  # as admin
    assert client.get(f"/api/v1/positions/{alice_pos_id}").status_code == 404
    resp = client.post(
        f"/api/v1/positions/{alice_pos_id}/add",
        json=_adjust_payload("1", "100"),
    )
    assert resp.status_code == 404
    resp = client.post(
        f"/api/v1/positions/{alice_pos_id}/reduce",
        json=_adjust_payload("1", "100"),
    )
    assert resp.status_code == 404
    assert client.delete(f"/api/v1/positions/{alice_pos_id}").status_code == 404


def test_list_include_closed(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="1", price="100")).json()
    pid = opened["data"]["id"]
    client.post(f"/api/v1/positions/{pid}/reduce", json=_adjust_payload("1", "110"))
    # Default excludes closed.
    assert client.get("/api/v1/positions").json()["total"] == 0
    # include_closed=1 returns it.
    assert client.get("/api/v1/positions?include_closed=1").json()["total"] == 1


@pytest.mark.asyncio
async def test_concurrent_adds_are_serialized(client: TestClient, test_password: str) -> None:
    """Two overlapping /add calls against the same position should
    both complete cleanly — the per-position lock keeps the weighted
    average math consistent. TestClient is sync but we validate the
    lock itself prevents reentry."""
    from app.ingestion.locks import get_position_lock

    _login(client, test_password)
    _add_watchlist(client, "SPY")
    opened = client.post("/api/v1/positions", json=_open_payload(shares="10", price="100")).json()
    pid = opened["data"]["id"]

    # Verify the lock is reusable across calls + the second grab
    # blocks until the first releases.
    first = await get_position_lock(pid)
    second = await get_position_lock(pid)
    assert first is second

    # Simulate held lock: the second acquire must wait (but finishes).
    await first.acquire()
    try:
        waiter = asyncio.create_task(second.acquire())
        await asyncio.sleep(0)  # let the task start
        assert not waiter.done()
    finally:
        first.release()
    await asyncio.wait_for(waiter, timeout=1.0)
    second.release()

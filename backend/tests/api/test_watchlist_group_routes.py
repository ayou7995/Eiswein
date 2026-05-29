"""Watchlist group routes — auth, CRUD, reorder, assignment."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_list_groups_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/watchlist/groups")
    assert resp.status_code == 401


def test_create_group_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/watchlist/groups", json={"name": "Watching"})
    assert resp.status_code == 401


def test_list_groups_starts_empty(client: TestClient, test_password: str) -> None:
    """Fresh admin user (created by main.py lifespan, no migrations run)
    has no groups — the seed step in migration 0017 only fires when the
    migrations themselves are applied (in-memory tests use Base.metadata.create_all)."""
    _login(client, test_password)
    resp = client.get("/api/v1/watchlist/groups")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"data": [], "total": 0}


def test_create_group_happy_path(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist/groups", json={"name": "Watching"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Watching"
    assert body["position"] == 0
    assert body["symbol_count"] == 0


def test_create_group_duplicate_returns_409(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist/groups", json={"name": "Watching"})
    resp = client.post("/api/v1/watchlist/groups", json={"name": "WATCHING"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "group_duplicate_name"


def test_create_group_name_too_long_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist/groups", json={"name": "x" * 33})
    assert resp.status_code == 422


def test_create_group_empty_name_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post("/api/v1/watchlist/groups", json={"name": ""})
    assert resp.status_code == 422


def test_rename_group_happy_path(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    create = client.post("/api/v1/watchlist/groups", json={"name": "Old"})
    gid = create.json()["id"]
    resp = client.patch(f"/api/v1/watchlist/groups/{gid}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_rename_unknown_returns_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.patch("/api/v1/watchlist/groups/999", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_group_returns_204(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    create = client.post("/api/v1/watchlist/groups", json={"name": "Watching"})
    gid = create.json()["id"]
    resp = client.delete(f"/api/v1/watchlist/groups/{gid}")
    assert resp.status_code == 204


def test_delete_unknown_returns_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/groups/999")
    assert resp.status_code == 404


def test_reorder_groups(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    a = client.post("/api/v1/watchlist/groups", json={"name": "A"}).json()["id"]
    b = client.post("/api/v1/watchlist/groups", json={"name": "B"}).json()["id"]
    c = client.post("/api/v1/watchlist/groups", json={"name": "C"}).json()["id"]

    resp = client.patch(
        "/api/v1/watchlist/groups/reorder",
        json={"ordered_ids": [c, a, b]},
    )
    assert resp.status_code == 200
    listing = client.get("/api/v1/watchlist/groups").json()
    assert [g["name"] for g in listing["data"]] == ["C", "A", "B"]


def test_reorder_unknown_id_returns_404(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    a = client.post("/api/v1/watchlist/groups", json={"name": "A"}).json()["id"]
    resp = client.patch(
        "/api/v1/watchlist/groups/reorder",
        json={"ordered_ids": [a, 999]},
    )
    assert resp.status_code == 404


def test_assign_watchlist_to_group(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    gid = client.post("/api/v1/watchlist/groups", json={"name": "Watching"}).json()["id"]

    resp = client.patch(
        "/api/v1/watchlist/NVDA/group",
        json={"group_id": gid},
    )
    assert resp.status_code == 200

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert item["group_id"] == gid
    assert item["group_name"] == "Watching"


def test_assign_watchlist_to_unknown_group_returns_404(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    resp = client.patch(
        "/api/v1/watchlist/NVDA/group",
        json={"group_id": 999},
    )
    assert resp.status_code == 404


def test_assign_unassigns_with_null_group_id(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    gid = client.post("/api/v1/watchlist/groups", json={"name": "Watching"}).json()["id"]
    client.patch("/api/v1/watchlist/NVDA/group", json={"group_id": gid})
    resp = client.patch("/api/v1/watchlist/NVDA/group", json={"group_id": None})
    assert resp.status_code == 200

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert item["group_id"] is None
    assert item["group_name"] is None


def test_delete_group_orphans_member_rows(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    gid = client.post("/api/v1/watchlist/groups", json={"name": "Watching"}).json()["id"]
    client.patch("/api/v1/watchlist/NVDA/group", json={"group_id": gid})

    resp = client.delete(f"/api/v1/watchlist/groups/{gid}")
    assert resp.status_code == 204

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert item["group_id"] is None


def test_list_groups_includes_symbol_count(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    client.post("/api/v1/watchlist", json={"symbol": "QQQ"})
    gid = client.post("/api/v1/watchlist/groups", json={"name": "Watching"}).json()["id"]
    client.patch("/api/v1/watchlist/NVDA/group", json={"group_id": gid})
    client.patch("/api/v1/watchlist/QQQ/group", json={"group_id": gid})

    listing = client.get("/api/v1/watchlist/groups").json()
    group = next(g for g in listing["data"] if g["id"] == gid)
    assert group["symbol_count"] == 2

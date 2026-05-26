"""Watchlist tag routes — auth, CRUD, attach/detach, color validation."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def test_list_tags_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/watchlist/tags")
    assert resp.status_code == 401


def test_create_tag_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "AI", "color": "#22C55E"},
    )
    assert resp.status_code == 401


def test_list_tags_starts_empty(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/watchlist/tags")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"data": [], "total": 0, "popular": []}


def test_create_tag_happy_path(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "AI", "color": "#22C55E"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "AI"
    assert body["color"] == "#22C55E"


def test_create_tag_invalid_color_returns_422(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    # Length-bound pydantic validation catches < 7-char colors before
    # the repository's regex check fires — both 422 with distinct codes.
    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "AI", "color": "red"},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "AI", "color": "#XYZ123"},  # 7 chars but not hex
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "tag_invalid_color"


def test_create_tag_name_too_long_returns_422(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "x" * 33, "color": "#22C55E"},
    )
    assert resp.status_code == 422


def test_create_tag_duplicate_returns_409(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"})
    resp = client.post(
        "/api/v1/watchlist/tags",
        json={"name": "ai", "color": "#FF0000"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "tag_duplicate_name"


def test_rename_tag(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    create = client.post(
        "/api/v1/watchlist/tags", json={"name": "Old", "color": "#22C55E"}
    )
    tid = create.json()["id"]
    resp = client.patch(f"/api/v1/watchlist/tags/{tid}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_recolor_tag(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    create = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    )
    tid = create.json()["id"]
    resp = client.patch(f"/api/v1/watchlist/tags/{tid}", json={"color": "#FF0000"})
    assert resp.status_code == 200
    assert resp.json()["color"] == "#FF0000"


def test_update_tag_rejects_bad_color(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    create = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    )
    tid = create.json()["id"]
    resp = client.patch(f"/api/v1/watchlist/tags/{tid}", json={"color": "#XYZ123"})
    assert resp.status_code == 422


def test_delete_tag_returns_204(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    create = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    )
    tid = create.json()["id"]
    resp = client.delete(f"/api/v1/watchlist/tags/{tid}")
    assert resp.status_code == 204


def test_delete_unknown_tag_returns_404(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.delete("/api/v1/watchlist/tags/999")
    assert resp.status_code == 404


def test_attach_tag_to_watchlist(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    tid = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()["id"]

    resp = client.post(f"/api/v1/watchlist/NVDA/tags/{tid}")
    assert resp.status_code == 200

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert [t["name"] for t in item["tags"]] == ["AI"]


def test_attach_is_idempotent(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    tid = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()["id"]

    client.post(f"/api/v1/watchlist/NVDA/tags/{tid}")
    resp = client.post(f"/api/v1/watchlist/NVDA/tags/{tid}")
    assert resp.status_code == 200

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert len(item["tags"]) == 1


def test_detach_tag_from_watchlist(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    tid = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()["id"]
    client.post(f"/api/v1/watchlist/NVDA/tags/{tid}")

    resp = client.delete(f"/api/v1/watchlist/NVDA/tags/{tid}")
    assert resp.status_code == 200

    listing = client.get("/api/v1/watchlist").json()
    item = next(i for i in listing["data"] if i["symbol"] == "NVDA")
    assert item["tags"] == []


def test_detach_is_idempotent(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    tid = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()["id"]
    # Detach without attach — no-op 200.
    resp = client.delete(f"/api/v1/watchlist/NVDA/tags/{tid}")
    assert resp.status_code == 200


def test_attach_to_unknown_symbol_returns_404(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    tid = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()["id"]
    resp = client.post(f"/api/v1/watchlist/NOPE/tags/{tid}")
    assert resp.status_code == 404


def test_attach_with_unknown_tag_returns_404(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    resp = client.post("/api/v1/watchlist/NVDA/tags/999")
    assert resp.status_code == 404


def test_list_tags_includes_popular(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    tag_a = client.post(
        "/api/v1/watchlist/tags", json={"name": "AI", "color": "#22C55E"}
    ).json()
    tag_b = client.post(
        "/api/v1/watchlist/tags", json={"name": "Semis", "color": "#FF0000"}
    ).json()
    client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    client.post("/api/v1/watchlist", json={"symbol": "TSM"})
    client.post(f"/api/v1/watchlist/NVDA/tags/{tag_a['id']}")
    client.post(f"/api/v1/watchlist/TSM/tags/{tag_a['id']}")
    client.post(f"/api/v1/watchlist/NVDA/tags/{tag_b['id']}")

    listing = client.get("/api/v1/watchlist/tags").json()
    assert [t["name"] for t in listing["popular"]] == ["AI", "Semis"]

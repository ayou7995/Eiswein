"""Auth routes — login, refresh, logout, IP lockout."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import COOKIE_ACCESS, COOKIE_REFRESH


def test_login_success_sets_cookies(client: TestClient, test_password: str) -> None:
    resp = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": test_password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "ok": True,
        "user": {"username": "admin", "is_admin": True},
    }
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_ACCESS in set_cookie
    assert COOKIE_REFRESH in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.lower()
    # Body must not contain the raw JWT.
    for token_key in (COOKIE_ACCESS, COOKIE_REFRESH):
        assert body.get(token_key) is None


def test_me_returns_current_user(client: TestClient, test_password: str) -> None:
    login = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": test_password},
    )
    assert login.status_code == 200
    resp = client.get("/api/v1/me")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "user": {"username": "admin", "is_admin": True},
    }


def test_me_without_cookie_returns_401(client: TestClient) -> None:
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401


def test_login_wrong_password_returns_401_envelope(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": "wrong-password-value"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_password"
    assert "attempts_remaining" in body["error"]["details"]


def test_login_missing_user_returns_401(client: TestClient, test_password: str) -> None:
    resp = client.post(
        "/api/v1/login",
        json={"username": "ghost", "password": test_password},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_password"


def test_login_ip_lockout_after_threshold(client: TestClient) -> None:
    for _ in range(3):
        resp = client.post(
            "/api/v1/login",
            json={"username": "admin", "password": "bad"},
        )
        assert resp.status_code == 401
    locked = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": "bad"},
    )
    assert locked.status_code == 403
    body = locked.json()
    assert body["error"]["code"] == "locked_out"
    assert body["error"]["details"]["retry_after_seconds"] > 0


def test_refresh_without_cookie_returns_401(client: TestClient) -> None:
    resp = client.post("/api/v1/refresh")
    assert resp.status_code == 401


def test_refresh_rotates_tokens(client: TestClient, test_password: str) -> None:
    login = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": test_password},
    )
    assert login.status_code == 200
    refresh_resp = client.post("/api/v1/refresh")
    assert refresh_resp.status_code == 200
    assert refresh_resp.json() == {"ok": True}
    set_cookie = refresh_resp.headers.get("set-cookie", "")
    assert COOKIE_ACCESS in set_cookie


def test_logout_clears_cookies(client: TestClient, test_password: str) -> None:
    client.post(
        "/api/v1/login",
        json={"username": "admin", "password": test_password},
    )
    resp = client.post("/api/v1/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    set_cookie = resp.headers.get("set-cookie", "")
    # Expired / cleared cookies appear as Max-Age=0 in Starlette output.
    assert "Max-Age=0" in set_cookie or 'eiswein_access=""' in set_cookie


def test_login_validation_error_uses_envelope(client: TestClient) -> None:
    resp = client.post("/api/v1/login", json={"username": "", "password": ""})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"

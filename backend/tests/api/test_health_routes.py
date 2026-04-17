"""Healthcheck contract (I23)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"]["status"] == "ok"
    assert "scheduler" in body
    assert "data_sources" in body


def test_security_headers_present(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("Content-Security-Policy", "").startswith("default-src 'self'")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Strict-Transport-Security")

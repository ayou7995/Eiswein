"""Log sanitizer redacts sensitive keys."""

from __future__ import annotations

from app.security.log_sanitizer import REDACTED, sanitize_log_payload, structlog_redactor


def test_redacts_top_level_password() -> None:
    out = sanitize_log_payload({"username": "a", "password": "hunter2"})
    assert out == {"username": "a", "password": REDACTED}


def test_redacts_nested_token() -> None:
    out = sanitize_log_payload({"meta": {"refresh_token": "s3cret"}, "ip": "1.1.1.1"})
    assert out == {"meta": {"refresh_token": REDACTED}, "ip": "1.1.1.1"}


def test_redacts_case_insensitively() -> None:
    out = sanitize_log_payload({"API_KEY": "abc", "SecretThing": "xyz"})
    assert out == {"API_KEY": REDACTED, "SecretThing": REDACTED}


def test_redacts_inside_list() -> None:
    out = sanitize_log_payload({"items": [{"password": "a"}, {"ok": True}]})
    assert out == {"items": [{"password": REDACTED}, {"ok": True}]}


def test_leaves_non_sensitive_keys() -> None:
    payload = {"user_id": 42, "path": "/api/v1/login", "status": 200}
    assert sanitize_log_payload(payload) == payload


def test_structlog_processor_mutates_event_dict() -> None:
    event: dict[str, object] = {
        "event": "login_attempt",
        "password": "hunter2",
        "details": {"token": "abcd"},
    }
    result = structlog_redactor(None, "info", event)
    assert result["password"] == REDACTED
    assert result["details"] == {"token": REDACTED}
    assert result["event"] == "login_attempt"

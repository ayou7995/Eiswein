# ruff: noqa: RUF001
"""bootstrap.py — unit tests for the pure helpers.

The smart-quote / dash test cases below intentionally embed those
exact codepoints to verify the normaliser. The blanket ``ruff: noqa``
above the docstring is the only way to keep ruff's
ambiguous-character heuristic from rejecting the file.


The interactive sections (admin password, FRED, SMTP, Schwab) drive
``input()`` and ``getpass.getpass`` directly; their integration is
exercised by walking the script manually before each release per the
AGENTS.md release checklist. These tests cover the value-shaping
helpers a CI pipeline can verify without faking a TTY.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "bootstrap.py"


@pytest.fixture(scope="module")
def bootstrap():
    """Load scripts/bootstrap.py as a module without invoking ``main()``."""
    spec = importlib.util.spec_from_file_location("bootstrap_module", BOOTSTRAP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_module"] = module
    spec.loader.exec_module(module)
    return module


def test_jwt_secret_is_url_safe_and_long(bootstrap) -> None:
    token = bootstrap._gen_jwt_secret()
    assert isinstance(token, str)
    # token_urlsafe(64) → 64 random bytes → ~86 url-safe chars.
    assert len(token) >= 64
    # url-safe alphabet — no '+', '/', or whitespace.
    assert all(c.isalnum() or c in {"-", "_"} for c in token)


def test_encryption_key_decodes_to_32_bytes(bootstrap) -> None:
    key = bootstrap._gen_encryption_key()
    raw = base64.urlsafe_b64decode(key)
    assert len(raw) == 32


def test_default_block_matches_settings_defaults(bootstrap) -> None:
    defaults = bootstrap._assemble_defaults()
    assert defaults["ENVIRONMENT"] == "production"
    assert defaults["DATABASE_URL"].startswith("sqlite:///")
    assert defaults["FRONTEND_URL"].startswith("http://")
    assert defaults["COOKIE_SECURE"] == "false"


def test_empty_smtp_block_disables_email(bootstrap) -> None:
    block = bootstrap._empty_smtp_block()
    assert block["SMTP_HOST"] == ""
    # All SMTP keys must exist so .env always has the same shape — no
    # "missing" keys that the runtime might trip over.
    assert {
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_TO",
        "SMTP_STARTTLS",
    } <= block.keys()


def test_empty_schwab_block_keeps_redirect_uri(bootstrap) -> None:
    """Even when Schwab is disabled we keep a syntactically valid
    redirect URI in the env so any future re-enable doesn't need a
    second visit to the dev portal."""
    block = bootstrap._empty_schwab_block()
    assert block["SCHWAB_CLIENT_ID"] == ""
    assert block["SCHWAB_CLIENT_SECRET"] == ""
    assert block["SCHWAB_REDIRECT_URI"].startswith("https://localhost:")
    assert "/api/v1/broker/schwab/callback" in block["SCHWAB_REDIRECT_URI"]


def test_render_env_emits_headed_sections(bootstrap) -> None:
    values = {
        **bootstrap._assemble_defaults(),
        "JWT_SECRET": "JWT123",
        "ENCRYPTION_KEY": "ENC456",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD_HASH": "$2b$12$hash",
        "FRED_API_KEY": "fredkey",
        **bootstrap._empty_smtp_block(),
        **bootstrap._empty_schwab_block(),
    }
    text = bootstrap._render_env(values)

    # Header + section markers present.
    assert text.startswith("# Eiswein .env")
    for header in ("Security", "Admin", "Environment", "Schwab", "SMTP"):
        assert f"=== {header}" in text

    # Each key=value pair is present on its own line.
    for key, value in values.items():
        assert f"{key}={value}" in text


def test_normalise_quotes_folds_smart_quotes_and_dashes(bootstrap) -> None:
    """macOS auto-substitution can turn straight quotes into curly ones
    during password entry. The login form does no such substitution,
    so we fold smart quotes back to ASCII before hashing."""
    raw = "“pass’word” – with — em-dash"
    out = bootstrap._normalise_quotes(raw)
    assert "“" not in out and "”" not in out
    assert "‘" not in out and "’" not in out
    assert "–" not in out and "—" not in out
    assert '"pass\'word"' in out


def test_normalise_quotes_passes_plain_ascii_unchanged(bootstrap) -> None:
    raw = "plain-ASCII'password\""
    assert bootstrap._normalise_quotes(raw) == raw


def test_find_unprintable_flags_control_chars(bootstrap) -> None:
    """Control chars (NUL, LF, TAB) almost always come from rich-text
    paste, and the user has no way to retype them at login."""
    assert bootstrap._find_unprintable("password\x00pasted") == 0x00
    assert bootstrap._find_unprintable("foo\nbar") == 0x0A
    assert bootstrap._find_unprintable("foo\tbar") == 0x09


def test_find_unprintable_flags_zero_width_chars(bootstrap) -> None:
    """Zero-width space + BOM are the classic invisible-paste foot-guns."""
    assert bootstrap._find_unprintable("foo​bar") == 0x200B
    assert bootstrap._find_unprintable("foo﻿bar") == 0xFEFF


def test_find_unprintable_returns_none_for_clean_input(bootstrap) -> None:
    assert bootstrap._find_unprintable("CorrectHorseBatteryStaple") is None
    assert bootstrap._find_unprintable("with spaces and !@#$%^&*()") is None


def test_render_env_handles_unicode_values(bootstrap) -> None:
    """A user might enter a name / sender with non-ASCII chars; the
    output must round-trip clean (UTF-8 file)."""
    values = {
        **bootstrap._assemble_defaults(),
        "JWT_SECRET": "x",
        "ENCRYPTION_KEY": "y",
        "ADMIN_USERNAME": "操作員",
        "ADMIN_PASSWORD_HASH": "$2b$12$h",
        "FRED_API_KEY": "",
        **bootstrap._empty_smtp_block(),
        **bootstrap._empty_schwab_block(),
    }
    text = bootstrap._render_env(values)
    assert "ADMIN_USERNAME=操作員" in text
    text.encode("utf-8")  # would raise if non-UTF-8 sneaks in

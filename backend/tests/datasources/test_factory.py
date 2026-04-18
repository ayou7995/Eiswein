"""DataSource factory — provider selection from settings."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import bcrypt

from app.config import Settings
from app.datasources.factory import build_data_source
from app.datasources.polygon_source import PolygonSource
from app.datasources.schwab_source import SchwabSource
from app.datasources.yfinance_source import YFinanceSource


def _settings(provider: str, tmp_path: Path) -> Settings:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
    pwd_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode("utf-8")
    return Settings(
        environment="development",
        database_url="sqlite:///:memory:",
        jwt_secret="test" * 20,
        encryption_key=key,  # type: ignore[arg-type]
        admin_username="admin",
        admin_password_hash=pwd_hash,  # type: ignore[arg-type]
        cookie_secure=False,
        cache_dir=tmp_path,
        data_source_provider=provider,  # type: ignore[arg-type]
    )


def test_factory_yfinance(tmp_path: Path) -> None:
    assert isinstance(build_data_source(_settings("yfinance", tmp_path)), YFinanceSource)


def test_factory_schwab(tmp_path: Path) -> None:
    assert isinstance(build_data_source(_settings("schwab", tmp_path)), SchwabSource)


def test_factory_polygon(tmp_path: Path) -> None:
    assert isinstance(build_data_source(_settings("polygon", tmp_path)), PolygonSource)

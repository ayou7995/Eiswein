"""Application configuration.

All config flows in through environment variables (pydantic-settings). In
production, SOPS + age decrypts secrets into env at container start; this
module is the only place that reads `os.environ`. The app refuses to start
when required admin seeding fields are missing (see A3 in
docs/STAFF_REVIEW_DECISIONS.md).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = "sqlite:///./data/eiswein.db"

    jwt_secret: SecretStr = Field(
        ...,
        description="Signing secret for JWT. Min 64 random chars.",
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_minutes: int = Field(default=15, ge=1, le=60)
    jwt_refresh_days: int = Field(default=7, ge=1, le=30)

    encryption_key: SecretStr = Field(
        ...,
        description="32-byte AES-256-GCM key, base64-url encoded.",
    )

    admin_username: str = Field(..., min_length=3, max_length=64)
    admin_password_hash: SecretStr = Field(
        ...,
        description="bcrypt hash produced by scripts/set_password.py",
    )

    rate_limit_login: str = "5/minute"
    rate_limit_api: str = "60/minute"
    login_lockout_threshold: int = Field(default=5, ge=1, le=20)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    login_global_alert_per_min: int = Field(default=20, ge=1, le=10000)

    # Trusted proxy list — Cloudflare IP range validation middleware
    # consumes this. Production loads it from Cloudflare's published ranges.
    trusted_proxies: list[str] = Field(
        default_factory=lambda: ["127.0.0.1/32", "::1/128"],
    )

    frontend_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"

    cookie_secure: bool = True
    cookie_domain: str | None = None

    # Data source selection (H1): yfinance is the v1 implementation;
    # schwab / polygon are interface stubs that raise NotImplementedError
    # on data methods — preserved so swapping providers is config-only.
    data_source_provider: Literal["yfinance", "schwab", "polygon"] = "yfinance"
    cache_dir: Path = Field(default=Path("./data/cache"))
    # Watchlist hard cap per B3 — configurable but default 100 to match
    # the yfinance bulk-download ceiling.
    watchlist_max_size: int = Field(default=100, ge=1, le=500)
    # FRED_API_KEY is not required when running without macro ingestion
    # (e.g. a single-ticker cold-start backfill). daily_update logs and
    # continues if it's missing or the FRED call fails (graceful
    # degradation per rule 14).
    fred_api_key: SecretStr | None = Field(default=None)

    @field_validator("admin_password_hash")
    @classmethod
    def _require_bcrypt_prefix(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw.startswith(("$2a$", "$2b$", "$2y$")):
            msg = "ADMIN_PASSWORD_HASH must be a bcrypt hash (use scripts/set_password.py)"
            raise ValueError(msg)
        return v

    @field_validator("encryption_key")
    @classmethod
    def _require_32_byte_key(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        try:
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, TypeError) as exc:
            msg = "ENCRYPTION_KEY must be base64-url encoded"
            raise ValueError(msg) from exc
        if len(decoded) != 32:
            msg = f"ENCRYPTION_KEY must decode to 32 bytes, got {len(decoded)}"
            raise ValueError(msg)
        return v

    @field_validator("jwt_secret")
    @classmethod
    def _require_long_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            msg = "JWT_SECRET must be at least 32 chars (64 recommended)"
            raise ValueError(msg)
        return v

    def encryption_key_bytes(self) -> bytes:
        raw = self.encryption_key.get_secret_value()
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency-friendly accessor. Cached so env reads happen once."""
    return Settings()  # type: ignore[call-arg]

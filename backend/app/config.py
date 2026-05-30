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

from pydantic import Field, SecretStr, computed_field, field_validator
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

    # How many trading days back gap detection scans for missing
    # DailyPrice rows. The default 300 covers all 12 indicators' lookback
    # windows (longest is 52-week RSI ≈ 260 days; SPX 200-MA needs 200).
    # Operators who want deeper historical context for the History page
    # or for back-testing-style analysis can bump this via .env (the
    # bootstrap wizard offers 1y / 2y / 5y presets, capped at 5y).
    # Daily-update gap detection is per-symbol, so a wider window only
    # costs extra fetch time on the FIRST run after the increase —
    # steady-state daily increments stay cheap regardless.
    backfill_window_trading_days: int = Field(default=300, ge=60, le=1260)
    # FRED_API_KEY is not required when running without macro ingestion
    # (e.g. a single-ticker cold-start backfill). daily_update logs and
    # continues if it's missing or the FRED call fails (graceful
    # degradation per rule 14).
    fred_api_key: SecretStr | None = Field(default=None)

    # Industry catalyst events live in a YAML file checked into the
    # repo (``docs/events.yaml``). When unset or pointing at a missing
    # file, calendar_sync skips the industry source entirely — earnings
    # + macro feeds still run. Production deploys override this with an
    # absolute path so the file ships beside the container image.
    industry_events_yaml: Path | None = Field(
        default=Path("docs/events.yaml"),
        description="Path to operator-curated industry catalyst events.",
    )

    # Gemini-backed industry event auto-sync (optional). When unset the
    # weekly ``industry_sync`` scheduler job and the manual-trigger admin
    # endpoint short-circuit with ``skipped_reason='no_api_key'`` — the
    # rest of the calendar (earnings, macro, YAML-curated industry) still
    # works. Get a free key from https://aistudio.google.com/apikey.
    gemini_api_key: SecretStr | None = Field(default=None)
    # Calendar UI treats industry events whose ``last_verified_at`` is
    # older than this many days as "資料可能過時" — drawer shows a banner
    # so the operator knows to spot-check the official site.
    industry_sync_stale_days: int = Field(default=21, ge=7, le=90)

    # Phase 6 — outbound email for daily summary + token expiry alerts.
    # Fully optional: when SMTP_HOST is unset, email jobs short-circuit
    # with a "not_configured" log and return so local dev + CI don't
    # need a real mail relay.
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None)
    smtp_password: SecretStr | None = Field(default=None)
    smtp_from: str | None = Field(default=None)
    smtp_to: str | None = Field(default=None)
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

    # --- Schwab (Broker OAuth) ---
    # Secrets are SecretStr so structlog/log_sanitizer can't accidentally
    # dump them. URLs are plain strings (not secrets). All fields are
    # optional: the app boots without Schwab credentials; routes and the
    # token-refresh scheduler register only when `schwab_enabled` is True.
    schwab_client_id: SecretStr | None = None
    schwab_client_secret: SecretStr | None = None
    schwab_redirect_uri: str = "https://127.0.0.1:8182/api/v1/broker/schwab/callback"
    schwab_oauth_authorize_url: str = "https://api.schwabapi.com/v1/oauth/authorize"
    schwab_oauth_token_url: str = "https://api.schwabapi.com/v1/oauth/token"
    schwab_api_base_url: str = "https://api.schwabapi.com/trader/v1"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def schwab_enabled(self) -> bool:
        """True iff both Schwab client id + secret are configured.

        Gating flag for conditional route/scheduler registration. Kept as
        a computed property so the rest of the app doesn't need to know
        the individual secret fields exist.
        """
        return self.schwab_client_id is not None and self.schwab_client_secret is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gemini_industry_sync_enabled(self) -> bool:
        """True iff a Gemini API key is configured.

        Gates the weekly ``industry_sync`` scheduler job and the admin
        manual-trigger endpoint. The Gemini-backed industry-event sync
        is fully optional — when disabled the rest of the calendar
        (earnings, macro, YAML industry) still works."""
        if self.gemini_api_key is None:
            return False
        return bool(self.gemini_api_key.get_secret_value().strip())

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

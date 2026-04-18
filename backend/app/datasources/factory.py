"""DataSource DI factory.

Resolves which provider to use based on ``settings.data_source_provider``.
Kept separate from individual provider modules so the composition root
(``main.py``) has a single, typed entry point for wiring.
"""

from __future__ import annotations

from app.config import Settings
from app.datasources.base import DataSource
from app.datasources.polygon_source import PolygonSource
from app.datasources.schwab_source import SchwabSource
from app.datasources.yfinance_source import YFinanceSource
from app.security.exceptions import EisweinError


class ConfigurationError(EisweinError):
    """Raised when the configured provider is unknown or unusable."""

    http_status = 500
    code = "configuration_error"
    message = "資料來源設定錯誤"


def build_data_source(settings: Settings) -> DataSource:
    provider = settings.data_source_provider
    match provider:
        case "yfinance":
            return YFinanceSource(cache_dir=settings.cache_dir)
        case "schwab":
            return SchwabSource()
        case "polygon":
            return PolygonSource()
        case _:  # pragma: no cover — guarded by Literal type on Settings
            raise ConfigurationError(
                details={"provider": provider},
                message=f"Unknown data_source_provider={provider!r}",
            )

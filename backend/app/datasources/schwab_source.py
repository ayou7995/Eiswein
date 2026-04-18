"""Schwab data-source stub (H1).

Schwab's data endpoints require OAuth credentials (stored encrypted in
:class:`BrokerCredential`). v1 ships the interface so we can swap
providers by config when v2 implements this — callers don't need
changes. Data methods raise :class:`NotImplementedError` to fail loud
and keep us from silently using a half-written provider.

The OAuth flow + credential storage IS in v1 (Settings page "Connect
Schwab"), but that lives in ``api/v1/broker_routes.py`` (Phase 5), not
here. This module is deliberately minimal.
"""

from __future__ import annotations

import pandas as pd

from app.datasources.base import DataSource, DataSourceHealth

_STUB_MESSAGE = (
    "Schwab data source deferred to v2. Use YFinanceSource for v1. "
    "Interface preserved so callers don't need changes when we migrate."
)


class SchwabSource(DataSource):
    @property
    def name(self) -> str:
        return "schwab"

    async def bulk_download(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        raise NotImplementedError(_STUB_MESSAGE)

    async def get_index_data(self, symbol: str, *, period: str = "2y") -> pd.DataFrame:
        raise NotImplementedError(_STUB_MESSAGE)

    async def health_check(self) -> DataSourceHealth:
        return DataSourceHealth(status="not_configured", detail=_STUB_MESSAGE)

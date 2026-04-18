"""Polygon.io data-source stub (H1).

Polygon is the planned v2 migration path for production-grade market
data (yfinance's ToS is ambiguous — see I10). v1 ships the interface
only; data methods raise :class:`NotImplementedError`.
"""

from __future__ import annotations

import pandas as pd

from app.datasources.base import DataSource, DataSourceHealth

_STUB_MESSAGE = (
    "Polygon data source deferred to v2. Use YFinanceSource for v1. "
    "Interface preserved so callers don't need changes when we migrate."
)


class PolygonSource(DataSource):
    @property
    def name(self) -> str:
        return "polygon"

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

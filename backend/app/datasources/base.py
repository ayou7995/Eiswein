"""Abstract DataSource contract.

Every provider returns per-symbol ``pandas.DataFrame`` objects with
normalized columns ``[open, high, low, close, volume]`` indexed by
timezone-aware ``DatetimeIndex`` in America/New_York (exchange-local).

Shape is enforced at the interface boundary so downstream indicators
can rely on a stable input contract — indicators should NOT re-validate
frame shape themselves (rule 7: DRY).

DataSourceHealth is a frozen Pydantic model returned by
``health_check()`` so operational state can be surfaced to the
``/api/v1/data/status`` endpoint without callers special-casing each
provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

HealthStatus = Literal["ok", "degraded", "not_configured", "error"]


class DataSourceHealth(BaseModel):
    """Immutable health snapshot (rule 11)."""

    model_config = ConfigDict(frozen=True)

    status: HealthStatus
    detail: str | None = None


class DataSource(ABC):
    """Provider-agnostic bulk + index OHLCV access.

    Implementations MUST:
    * return DataFrames with lowercase column names: open, high, low, close, volume
    * use a ``DatetimeIndex`` with tz=``America/New_York``
    * raise :class:`app.security.exceptions.DataSourceError` on upstream failure
      (caller decides between retry and user-facing error)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (``yfinance``, ``fred``, ``schwab`` ...)."""

    @abstractmethod
    async def bulk_download(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for every symbol in ONE upstream request.

        `period` accepts yfinance-style strings ("2y", "1y", "6mo").
        Implementations may ignore ``period`` when the provider takes
        explicit start/end instead.
        """

    @abstractmethod
    async def get_index_data(
        self,
        symbol: str,
        *,
        period: str = "2y",
    ) -> pd.DataFrame:
        """Fetch an index series (SPX / VIX / DXY proxy).

        Single-symbol convenience; implementations should typically
        delegate to :meth:`bulk_download` and pop the one key.
        """

    @abstractmethod
    async def health_check(self) -> DataSourceHealth:
        """Lightweight probe. Never raises — always returns a status."""

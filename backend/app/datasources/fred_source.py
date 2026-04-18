"""FRED macro series fetcher.

FRED exposes ~120 req/min — generous for our use, but we still batch
per-series fetches through tenacity so transient network blips don't
abort ``daily_update``.

Default series (overridable via ``series_ids``):
* ``DGS10``   — 10-Year Treasury constant maturity
* ``DGS2``    — 2-Year Treasury constant maturity
* ``DTWEXBGS`` — Trade-Weighted USD (DXY proxy — FRED lacks raw DXY)
* ``FEDFUNDS`` — Effective Federal Funds Rate
* ``VIXCLS``  — CBOE VIX daily close (also available on yfinance but
  FRED is the FRED-scoped counterpart for macro dashboards)

Indicators consume these as DataFrames indexed by ``date`` with a
single ``value`` column — matching the :class:`MacroIndicator` row
shape exactly, so the ingestion layer can UPSERT without reshaping.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pandas as pd
import structlog
from fredapi import Fred
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.datasources.base import DataSource, DataSourceHealth
from app.security.exceptions import DataSourceError

logger = structlog.get_logger("eiswein.datasources.fred")

DEFAULT_SERIES_IDS: tuple[str, ...] = (
    "DGS10",
    "DGS2",
    "DTWEXBGS",
    "FEDFUNDS",
    "VIXCLS",
)

_HEALTH_PROBE_SERIES = "DGS10"


class FREDSource(DataSource):
    """Pulls FRED economic series via ``fredapi.Fred``.

    Unlike yfinance this provider fetches ONE series per call — FRED
    has no bulk endpoint. We parallelize with asyncio.gather when
    multiple series are requested.
    """

    def __init__(self, *, api_key: str, default_series: Sequence[str] | None = None) -> None:
        if not api_key:
            raise DataSourceError(details={"reason": "fred_api_key_missing"})
        self._client = Fred(api_key=api_key)
        self._default_series: tuple[str, ...] = (
            tuple(default_series) if default_series else DEFAULT_SERIES_IDS
        )

    @property
    def name(self) -> str:
        return "fred"

    @property
    def default_series(self) -> tuple[str, ...]:
        return self._default_series

    async def bulk_download(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple FRED series concurrently.

        ``period`` maps to a rough observation_start offset; FRED
        returns the full history by default and we let downstream
        consumers slice. For the v1 we take everything FRED has.
        """
        if not symbols:
            return {}
        cleaned = [s.strip().upper() for s in symbols if s.strip()]
        coros = [self._fetch_one_async(sid) for sid in cleaned]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[str, pd.DataFrame] = {}
        for sid, result in zip(cleaned, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "fred_series_failed",
                    series=sid,
                    error_type=type(result).__name__,
                    error=str(result),
                )
                out[sid] = pd.DataFrame()
                continue
            out[sid] = result
        return out

    async def get_index_data(self, symbol: str, *, period: str = "2y") -> pd.DataFrame:
        frame = await self._fetch_one_async(symbol.upper())
        if frame.empty:
            raise DataSourceError(details={"reason": "no_data", "series": symbol})
        return frame

    async def health_check(self) -> DataSourceHealth:
        try:
            frame = await self._fetch_one_async(_HEALTH_PROBE_SERIES)
        except DataSourceError as exc:
            return DataSourceHealth(status="error", detail=str(exc.details))
        if frame.empty:
            return DataSourceHealth(status="degraded", detail="empty probe response")
        return DataSourceHealth(status="ok")

    async def _fetch_one_async(self, series_id: str) -> pd.DataFrame:
        try:
            return await asyncio.to_thread(_fetch_with_retry, self._client, series_id)
        except DataSourceError:
            raise
        except Exception as exc:
            raise DataSourceError(
                details={"reason": "fred_error", "series": series_id, "error": str(exc)}
            ) from exc


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _fetch_with_retry(client: Fred, series_id: str) -> pd.DataFrame:
    """Single series fetch. Normalizes to date-indexed single-column frame.

    Date index is a ``DatetimeIndex`` (not plain date objects) so the
    caller can iterate with ``pd.Timestamp`` semantics matching the
    yfinance adapter.
    """
    series = client.get_series(series_id)
    if series is None or len(series) == 0:
        return pd.DataFrame(columns=["value"])
    frame = pd.DataFrame({"value": series})
    frame.index = pd.to_datetime(frame.index)
    return frame.dropna(how="all")

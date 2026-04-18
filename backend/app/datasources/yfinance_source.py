"""yfinance implementation of :class:`DataSource`.

Non-negotiable invariants (see CLAUDE.md + STAFF_REVIEW_DECISIONS.md I7):
* ONE upstream ``yf.download`` per call — never loop per-ticker.
* ``threads=False`` — Yahoo's anti-abuse triggers on multi-threaded
  clients, causing sporadic empty frames.
* ``auto_adjust=True`` — ``close`` is split+dividend-adjusted. Matches
  how Position.avg_cost is recorded (manual, post-split).
* Parquet cache written BEFORE parsing so that on parse failure,
  tenacity retries hit cache rather than re-hammering the upstream.
* Cache eviction: files older than 7 days deleted lazily on every call
  (I16 — retention 7 days).

Retry policy uses :mod:`tenacity` with exponential jitter. We retry only
transient network / timeout errors; empty-frame responses and parse
errors flag the symbol as ``delisted_or_invalid`` and surface as
:class:`DataSourceError` so the API layer can update
``watchlist.data_status`` accordingly (I18).
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import structlog
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.datasources.base import DataSource, DataSourceHealth
from app.security.exceptions import DataSourceError

logger = structlog.get_logger("eiswein.datasources.yfinance")

_CACHE_TTL = timedelta(days=7)
_MARKET_TZ = "America/New_York"
_HEALTH_PROBE_SYMBOL = "SPY"


def _symbols_hash(symbols: list[str]) -> str:
    """Stable short hash of the sorted symbol set."""
    joined = ",".join(sorted(s.upper() for s in symbols))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Lowercase OHLCV columns + tz-aware index (America/New_York)."""
    if raw.empty:
        return raw
    df = raw.copy()
    df.columns = [str(c).lower() for c in df.columns]
    keep = ["open", "high", "low", "close", "volume"]
    present = [c for c in keep if c in df.columns]
    df = df[present]
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = (
            df.index.tz_localize(_MARKET_TZ)
            if df.index.tz is None
            else df.index.tz_convert(_MARKET_TZ)
        )
    return df


def find_and_remove_old_parquets(cache_root: Path, *, ttl: timedelta = _CACHE_TTL) -> int:
    """Delete cache files older than ``ttl``. Returns count removed.

    Exposed at module level for the daily-backup job to call during
    maintenance (I16).
    """
    if not cache_root.exists():
        return 0
    cutoff = datetime.now(UTC).timestamp() - ttl.total_seconds()
    removed = 0
    for path in cache_root.glob("*.parquet"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("cache_evict_failed", path=str(path), error=str(exc))
    return removed


class YFinanceSource(DataSource):
    """Bulk OHLCV via yfinance with parquet cache + tenacity retry."""

    def __init__(self, *, cache_dir: Path) -> None:
        self._cache_root = Path(cache_dir) / "yfinance"
        self._cache_root.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "yfinance"

    def _cache_path_for(self, symbols: list[str]) -> Path:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._cache_root / f"{today}_{_symbols_hash(symbols)}.parquet"

    async def bulk_download(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        cleaned = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not cleaned:
            return {}

        find_and_remove_old_parquets(self._cache_root)

        try:
            raw = await asyncio.to_thread(
                self._fetch_with_cache, cleaned, period=period
            )
        except DataSourceError:
            raise
        except Exception as exc:  # network after retries exhausted
            logger.warning(
                "yfinance_bulk_failed",
                symbols=cleaned,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise DataSourceError(
                details={"reason": "upstream_error", "error": str(exc)}
            ) from exc

        return _split_bulk_frame(raw, cleaned)

    async def get_index_data(self, symbol: str, *, period: str = "2y") -> pd.DataFrame:
        out = await self.bulk_download([symbol], period=period)
        frame = out.get(symbol.upper())
        if frame is None or frame.empty:
            raise DataSourceError(
                details={"reason": "delisted_or_invalid", "symbol": symbol}
            )
        return frame

    async def health_check(self) -> DataSourceHealth:
        try:
            result = await self.bulk_download([_HEALTH_PROBE_SYMBOL], period="5d")
        except DataSourceError as exc:
            return DataSourceHealth(status="error", detail=str(exc.details))
        if _HEALTH_PROBE_SYMBOL in result and not result[_HEALTH_PROBE_SYMBOL].empty:
            return DataSourceHealth(status="ok")
        return DataSourceHealth(status="degraded", detail="empty probe frame")

    # --- Internal helpers (executed in a worker thread) ---

    def _fetch_with_cache(
        self, symbols: list[str], *, period: str
    ) -> pd.DataFrame:
        cache_path = self._cache_path_for(symbols)
        if cache_path.exists():
            try:
                return pd.read_parquet(cache_path)
            except Exception as exc:
                logger.warning(
                    "yfinance_cache_read_failed", path=str(cache_path), error=str(exc)
                )
                try:
                    cache_path.unlink()
                except OSError:  # best-effort eviction of a corrupt cache entry
                    pass

        frame = _download_with_retry(symbols, period=period)
        try:
            frame.to_parquet(cache_path)
        except Exception as exc:
            logger.warning(
                "yfinance_cache_write_failed", path=str(cache_path), error=str(exc)
            )
        return frame


# Retries only transient network-class failures; ValueError / KeyError from
# downstream parsing are surfaced immediately so we don't burn backoff time
# on deterministic failures.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _download_with_retry(symbols: list[str], *, period: str) -> pd.DataFrame:
    """Single bulk upstream call. Returns raw yfinance multi-ticker frame."""
    kwargs: dict[str, Any] = {
        "tickers": " ".join(symbols),
        "period": period,
        "group_by": "ticker",
        "threads": False,
        "progress": False,
        "auto_adjust": True,
    }
    frame = yf.download(**kwargs)
    if not isinstance(frame, pd.DataFrame):
        raise DataSourceError(details={"reason": "unexpected_response_type"})
    return frame


def _split_bulk_frame(
    raw: pd.DataFrame, symbols: list[str]
) -> dict[str, pd.DataFrame]:
    """Turn a yfinance bulk frame into per-symbol DataFrames.

    Single-symbol downloads return a flat column index; multi-symbol
    downloads return a MultiIndex (symbol, field). We normalize both to
    the same contract so indicators downstream don't care which path
    populated them.
    """
    if raw.empty:
        return {sym: raw for sym in symbols}

    result: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        # yfinance's MultiIndex with group_by="ticker" is (symbol, field).
        for sym in symbols:
            try:
                sub = raw[sym]
            except KeyError:
                result[sym] = pd.DataFrame()
                continue
            if not isinstance(sub, pd.DataFrame):
                # Shouldn't happen with our group_by but be defensive.
                result[sym] = pd.DataFrame()
                continue
            normalized = _normalize_frame(sub).dropna(how="all")
            result[sym] = normalized
        return result

    # Flat frame → single symbol case.
    only = symbols[0] if len(symbols) == 1 else symbols[0]
    result[only] = _normalize_frame(raw).dropna(how="all")
    for sym in symbols[1:]:
        result[sym] = pd.DataFrame()
    return result

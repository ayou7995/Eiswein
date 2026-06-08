"""yfinance implementation of :class:`DataSource`.

Non-negotiable invariants (see CLAUDE.md + STAFF_REVIEW_DECISIONS.md I7):
* ONE upstream ``yf.download`` per call — never loop per-ticker.
* ``threads=False`` — Yahoo's anti-abuse triggers on multi-threaded
  clients, causing sporadic empty frames.
* ``auto_adjust=True`` — ``close`` is split+dividend-adjusted. Matches
  how Position.avg_cost is recorded (manual, post-split).

Two freshness contracts (2026-06 architectural fix):
* **History fetch** (``_fetch_history_with_cache``) — closed bars only,
  EXCLUDES today. Cached aggressively under the per-day parquet file;
  same symbol+period set returns the cached frame for the rest of the
  day. Idempotent — Yahoo's closed-day data never changes.
* **Today fetch** (``fetch_today_running``) — today's running daily bar
  only. NEVER cached — value mutates every minute during market hours.

``bulk_download`` composes the two so callers get "everything up to now"
with one method, while the cache continues to do its job for the 99%
historical case. This bifurcation is what prevents the morning's cache
write from trapping a stale partial bar for the rest of the trading
session (the original bug that motivated the split).

Retry policy uses :mod:`tenacity` with exponential jitter. We retry only
transient network / timeout errors; empty-frame responses and parse
errors flag the symbol as ``delisted_or_invalid`` and surface as
:class:`DataSourceError` so the API layer can update
``watchlist.data_status`` accordingly (I18).
"""

from __future__ import annotations

import asyncio
import contextlib
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

    def _cache_path_for(self, symbols: list[str], *, period: str) -> Path:
        # Cache key includes ``period`` because the same symbol set at
        # different windows (e.g. ``5d`` for pre-flight validation vs
        # ``2y`` for cold-start backfill) must not share a file —
        # otherwise the shorter window poisons the longer one.
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._cache_root / f"{today}_{period}_{_symbols_hash(symbols)}.parquet"

    async def bulk_download(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        """Cached history + always-fresh today's running bar.

        Composes :meth:`_fetch_history_with_cache` (closed bars, parquet
        cached) with :meth:`fetch_today_running` (today's running daily
        bar, never cached). Manual refresh + scheduled job both call
        this; the cache makes repeats cheap while today's row is always
        the latest yfinance has (~15 min Yahoo delay during market hours).
        """
        if not symbols:
            return {}
        cleaned = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not cleaned:
            return {}

        find_and_remove_old_parquets(self._cache_root)

        try:
            raw_history = await asyncio.to_thread(
                self._fetch_history_with_cache, cleaned, period=period
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
            # Upstream exception details stay in structured logs only (see the
            # logger.warning above). The client envelope carries just enough
            # to route the UI error — never the raw library traceback string,
            # which can leak internal URLs / auth-fragment hints.
            raise DataSourceError(details={"reason": "upstream_error"}) from exc

        history_per_symbol = _split_bulk_frame(raw_history, cleaned)

        # Today's running bar is best-effort — a transient yfinance hiccup
        # here must not break the whole call. Caller is happy with just
        # history if today fails to fetch.
        try:
            today_per_symbol = await self.fetch_today_running(cleaned)
        except Exception as exc:
            logger.warning(
                "yfinance_today_fetch_failed",
                symbols=cleaned,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            today_per_symbol = {}

        return _merge_history_and_today(history_per_symbol, today_per_symbol)

    async def fetch_today_running(
        self,
        symbols: list[str],
    ) -> dict[str, pd.DataFrame]:
        """Today's running daily OHLCV bar — no cache, fresh every call.

        Yahoo serves an in-progress daily bar during market hours that
        updates roughly every 15 minutes. Outside market hours the same
        endpoint returns the last completed trading day. Returns an
        empty frame for symbols Yahoo has no data on (typos, delistings,
        index symbols that don't support daily resolution).
        """
        if not symbols:
            return {}
        cleaned = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not cleaned:
            return {}

        try:
            raw = await asyncio.to_thread(
                _download_with_retry, cleaned, period="1d", interval="1d"
            )
        except Exception as exc:
            logger.warning(
                "yfinance_today_running_failed",
                symbols=cleaned,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return dict.fromkeys(cleaned, pd.DataFrame())

        return _split_bulk_frame(raw, cleaned)

    async def get_index_data(self, symbol: str, *, period: str = "2y") -> pd.DataFrame:
        out = await self.bulk_download([symbol], period=period)
        frame = out.get(symbol.upper())
        if frame is None or frame.empty:
            raise DataSourceError(details={"reason": "delisted_or_invalid", "symbol": symbol})
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

    def _fetch_history_with_cache(self, symbols: list[str], *, period: str) -> pd.DataFrame:
        """Cached fetch of CLOSED daily bars (excludes today).

        Critical: we strip today's row BEFORE writing the parquet so a
        6:30am-ET write doesn't trap a stale-by-noon partial bar for
        the rest of the trading session. Today's running bar is served
        by ``fetch_today_running`` on every call.
        """
        cache_path = self._cache_path_for(symbols, period=period)
        if cache_path.exists():
            try:
                return pd.read_parquet(cache_path)
            except Exception as exc:
                logger.warning("yfinance_cache_read_failed", path=str(cache_path), error=str(exc))
                with contextlib.suppress(OSError):
                    cache_path.unlink()

        frame = _download_with_retry(symbols, period=period)
        frame_closed = _strip_today(frame)
        try:
            frame_closed.to_parquet(cache_path)
        except Exception as exc:
            logger.warning("yfinance_cache_write_failed", path=str(cache_path), error=str(exc))
        return frame_closed


# Retries only transient network-class failures; ValueError / KeyError from
# downstream parsing are surfaced immediately so we don't burn backoff time
# on deterministic failures.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _download_with_retry(
    symbols: list[str], *, period: str, interval: str = "1d"
) -> pd.DataFrame:
    """Single bulk upstream call. Returns raw yfinance multi-ticker frame.

    ``interval`` defaults to daily; intraday refresh passes ``5m`` to
    pull the most recent bar of indices like ``^VIX`` / ``^VIX3M``."""
    kwargs: dict[str, Any] = {
        "tickers": " ".join(symbols),
        "period": period,
        "interval": interval,
        "group_by": "ticker",
        "threads": False,
        "progress": False,
        "auto_adjust": True,
    }
    frame = yf.download(**kwargs)
    if not isinstance(frame, pd.DataFrame):
        raise DataSourceError(details={"reason": "unexpected_response_type"})
    return frame


def _strip_today(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop any rows dated today (NYSE timezone) from a yfinance frame.

    The cache stores only closed bars — today's row is fetched fresh on
    every call. Without this strip, the 6:30am-ET scheduled job's cache
    write would trap a partial bar for the rest of the day.
    """
    if raw.empty or not isinstance(raw.index, pd.DatetimeIndex):
        return raw
    if raw.index.tz is not None:
        idx_dates = raw.index.tz_convert(_MARKET_TZ).date
    else:
        idx_dates = raw.index.date
    today_et = pd.Timestamp.now(tz=_MARKET_TZ).date()
    mask = idx_dates < today_et
    return raw.loc[mask]


def _merge_history_and_today(
    history: dict[str, pd.DataFrame],
    today: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Per-symbol concat of cached history + fresh today's bar.

    If a symbol has only history (e.g. yfinance failed for today's
    fetch), return history alone. If a symbol has only today (rare —
    cold-start during market hours), return today alone. When both are
    present we concat and drop any duplicate index rows preferring the
    today value — yfinance's today bar is the canonical current state
    if both sources happen to overlap on the closing tick.
    """
    out: dict[str, pd.DataFrame] = {}
    for sym, hist in history.items():
        today_frame = today.get(sym)
        if today_frame is None or today_frame.empty:
            out[sym] = hist
            continue
        if hist is None or hist.empty:
            out[sym] = today_frame
            continue
        combined = pd.concat([hist, today_frame])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        out[sym] = combined
    # Symbols that exist only in `today` (e.g. first call ever during
    # market hours) still need a slot in the output.
    for sym, today_frame in today.items():
        if sym not in out:
            out[sym] = today_frame
    return out


def _split_bulk_frame(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
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

    # Flat frame → single-symbol case. Multi-symbol bulk downloads always
    # return a MultiIndex frame, so reaching this branch with len>1 means
    # yfinance changed its response shape — log loudly so the regression
    # is visible before indicators compute on empty data for all but the
    # first ticker.
    if len(symbols) > 1:
        logger.warning(
            "yfinance_unexpected_flat_frame",
            symbols=symbols,
            hint="Expected MultiIndex for multi-ticker download",
        )
    only = symbols[0]
    result[only] = _normalize_frame(raw).dropna(how="all")
    for sym in symbols[1:]:
        result[sym] = pd.DataFrame()
    return result

"""YFinanceSource — bulk call signature, cache, retries, eviction."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.datasources.yfinance_source import (
    YFinanceSource,
    _split_bulk_frame,
    _symbols_hash,
    find_and_remove_old_parquets,
)
from app.security.exceptions import DataSourceError


def _bulk_frame(symbols: list[str], days: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2026-04-01", periods=days, freq="B", tz="America/New_York")
    rng = np.random.default_rng(seed=7)
    arrays = []
    columns = []
    for sym in symbols:
        base = 100 + np.cumsum(rng.normal(0, 1.0, size=days))
        arrays.append(base)
        columns.append((sym, "Open"))
        arrays.append(base + 1)
        columns.append((sym, "High"))
        arrays.append(base - 1)
        columns.append((sym, "Low"))
        arrays.append(base + 0.5)
        columns.append((sym, "Close"))
        arrays.append(rng.integers(1_000_000, 5_000_000, size=days).astype(np.int64))
        columns.append((sym, "Volume"))
    frame = pd.DataFrame(
        {col: arr for col, arr in zip(columns, arrays, strict=True)},
        index=idx,
    )
    frame.columns = pd.MultiIndex.from_tuples(columns)
    return frame


def test_symbols_hash_is_order_independent() -> None:
    assert _symbols_hash(["SPY", "AAPL"]) == _symbols_hash(["aapl", "spy"])
    assert _symbols_hash(["SPY"]) != _symbols_hash(["SPY", "QQQ"])


@pytest.mark.asyncio
async def test_bulk_download_calls_yfinance_with_required_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_history: dict[str, object] = {}

    def fake_download(**kwargs: object) -> pd.DataFrame:
        # The bifurcated bulk_download fires TWO yfinance calls per
        # invocation: the cached history (period as-passed) plus
        # ``fetch_today_running`` (period='1d'). We snapshot only the
        # first so the historical-call kwarg contract stays asserted.
        if "period" in kwargs and kwargs["period"] != "1d":
            captured_history.update(kwargs)
        return _bulk_frame(["SPY", "AAPL"])

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)

    source = YFinanceSource(cache_dir=tmp_path)
    out = await source.bulk_download(["spy", "aapl"], period="2y")

    assert captured_history["threads"] is False
    assert captured_history["auto_adjust"] is True
    assert captured_history["progress"] is False
    assert captured_history["group_by"] == "ticker"
    assert captured_history["period"] == "2y"
    assert captured_history["tickers"] == "AAPL SPY"

    assert set(out.keys()) == {"AAPL", "SPY"}
    for frame in out.values():
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.tz is not None


@pytest.mark.asyncio
async def test_bulk_download_history_path_uses_parquet_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The history (closed-bars) portion of bulk_download must be served
    from the parquet cache on repeated calls — only today's running bar
    is refetched. So total yfinance calls = 1 history + 2 today-running = 3."""
    call_count = {"history": 0, "today": 0}

    def fake_download(**kwargs: object) -> pd.DataFrame:
        if kwargs.get("period") == "1d":
            call_count["today"] += 1
        else:
            call_count["history"] += 1
        return _bulk_frame(["SPY"])

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)

    await source.bulk_download(["SPY"], period="1y")
    await source.bulk_download(["SPY"], period="1y")

    assert call_count["history"] == 1, "history must hit cache after first call"
    assert call_count["today"] == 2, "today bar must refetch every call"
    cache_files = list((tmp_path / "yfinance").glob("*.parquet"))
    assert len(cache_files) == 1


@pytest.mark.asyncio
async def test_bulk_download_empty_symbols_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(**_kwargs: object) -> pd.DataFrame:
        raise AssertionError("should not be called for empty input")

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)
    assert await source.bulk_download([], period="1y") == {}


@pytest.mark.asyncio
async def test_bulk_download_raises_data_source_error_on_network_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_fail(**_kwargs: object) -> pd.DataFrame:
        raise ConnectionError("yahoo down")

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", always_fail)
    source = YFinanceSource(cache_dir=tmp_path)
    with pytest.raises(DataSourceError):
        await source.bulk_download(["SPY"], period="1y")


@pytest.mark.asyncio
async def test_bulk_download_retries_transient_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = {"n": 0}

    def flaky(**_kwargs: object) -> pd.DataFrame:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionError("transient")
        return _bulk_frame(["SPY"])

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", flaky)
    # Shrink tenacity's sleep so the retry test stays under a second.
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)

    source = YFinanceSource(cache_dir=tmp_path)
    out = await source.bulk_download(["SPY"], period="1y")
    assert attempts["n"] >= 2
    assert "SPY" in out
    assert not out["SPY"].empty


@pytest.mark.asyncio
async def test_get_index_data_raises_on_empty_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(**_kwargs: object) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)
    with pytest.raises(DataSourceError) as excinfo:
        await source.get_index_data("DELISTED")
    assert excinfo.value.details.get("reason") == "delisted_or_invalid"


@pytest.mark.asyncio
async def test_health_check_returns_ok_when_probe_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.datasources.yfinance_source.yf.download",
        lambda **_: _bulk_frame(["SPY"]),
    )
    source = YFinanceSource(cache_dir=tmp_path)
    health = await source.health_check()
    assert health.status == "ok"


@pytest.mark.asyncio
async def test_health_check_reports_error_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_fail(**_kwargs: object) -> pd.DataFrame:
        raise ConnectionError("yahoo down")

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", always_fail)
    source = YFinanceSource(cache_dir=tmp_path)
    health = await source.health_check()
    assert health.status == "error"


def test_find_and_remove_old_parquets_evicts_stale_entries(tmp_path: Path) -> None:
    root = tmp_path / "yf"
    root.mkdir()
    fresh = root / "fresh.parquet"
    stale = root / "stale.parquet"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    past = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(stale, (past, past))

    removed = find_and_remove_old_parquets(root, ttl=timedelta(days=7))
    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_split_bulk_frame_handles_multi_index() -> None:
    raw = _bulk_frame(["SPY", "QQQ"])
    out = _split_bulk_frame(raw, ["SPY", "QQQ"])
    assert set(out.keys()) == {"SPY", "QQQ"}
    for frame in out.values():
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


def test_split_bulk_frame_empty_returns_empty_per_symbol() -> None:
    empty = pd.DataFrame()
    out = _split_bulk_frame(empty, ["AAA", "BBB"])
    assert out == {"AAA": empty, "BBB": empty}


# --- Bifurcation: cache-history excludes today, fetch_today_running uncached ---


def _bulk_frame_with_today(symbols: list[str], today_et) -> pd.DataFrame:
    """Like ``_bulk_frame`` but the last bar is today (NYSE tz)."""
    yesterday = pd.Timestamp(today_et) - pd.Timedelta(days=1)
    idx = pd.DatetimeIndex(
        [yesterday, pd.Timestamp(today_et)], tz="America/New_York"
    )
    rows = []
    columns: list[tuple[str, str]] = []
    for sym in symbols:
        rows.append([100.0, 101.0])  # Open
        columns.append((sym, "Open"))
        rows.append([102.0, 103.0])  # High
        columns.append((sym, "High"))
        rows.append([99.0, 100.0])  # Low
        columns.append((sym, "Low"))
        rows.append([101.5, 102.5])  # Close
        columns.append((sym, "Close"))
        rows.append([1_000_000, 1_500_000])  # Volume
        columns.append((sym, "Volume"))
    frame = pd.DataFrame(
        {col: rows[i] for i, col in enumerate(columns)},
        index=idx,
    )
    frame.columns = pd.MultiIndex.from_tuples(columns)
    return frame


@pytest.mark.asyncio
async def test_history_cache_strips_today_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 6:30am-ET morning cache write must NOT trap today's partial
    bar — otherwise the rest of the day's manual refreshes silently
    serve a stale snapshot."""
    today_et = pd.Timestamp.now(tz="America/New_York").normalize()

    def fake_download(**_kwargs: object) -> pd.DataFrame:
        return _bulk_frame_with_today(["SPY"], today_et)

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)

    # Run a fetch so the cache is populated.
    await source.bulk_download(["SPY"], period="2y")

    # Inspect the cache file directly — it must NOT contain a row dated today.
    cache_files = list((tmp_path / "yfinance").glob("*.parquet"))
    assert len(cache_files) == 1
    cached = pd.read_parquet(cache_files[0])
    if not cached.empty:
        if cached.index.tz is not None:
            row_dates = cached.index.tz_convert("America/New_York").date
        else:
            row_dates = cached.index.date
        assert today_et.date() not in set(row_dates), (
            "cache contains today's partial bar — would trap stale state until tomorrow"
        )


@pytest.mark.asyncio
async def test_bulk_download_composes_cached_history_with_fresh_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manual refresh during market hours must see today's bar even if
    the morning cache already exists. The cached history is for the
    closed bars; today is a separate uncached fetch."""
    today_et = pd.Timestamp.now(tz="America/New_York").normalize()
    call_count = {"n": 0}

    def fake_download(**kwargs: object) -> pd.DataFrame:
        call_count["n"] += 1
        return _bulk_frame_with_today(["SPY"], today_et)

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)

    # First call: writes cache + fetches today.
    first = await source.bulk_download(["SPY"], period="2y")
    spy = first["SPY"]
    if not spy.empty:
        if spy.index.tz is not None:
            dates = set(spy.index.tz_convert("America/New_York").date)
        else:
            dates = set(spy.index.date)
        assert today_et.date() in dates, "today's bar missing from merged output"

    # Second call within the same day must STILL refetch today even though
    # the parquet cache exists for the history.
    calls_before = call_count["n"]
    await source.bulk_download(["SPY"], period="2y")
    assert call_count["n"] > calls_before, (
        "today's bar must be refetched on every call, not served from cache"
    )


@pytest.mark.asyncio
async def test_fetch_today_running_never_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fetch_today_running`` is the always-fresh path — must NOT write
    any parquet, must hit yfinance every time it's called."""
    call_count = {"n": 0}

    def fake_download(**_kwargs: object) -> pd.DataFrame:
        call_count["n"] += 1
        today_et = pd.Timestamp.now(tz="America/New_York").normalize()
        return _bulk_frame_with_today(["SPY"], today_et)

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)

    await source.fetch_today_running(["SPY"])
    await source.fetch_today_running(["SPY"])
    assert call_count["n"] == 2, "fetch_today_running must not cache"
    assert not list((tmp_path / "yfinance").glob("*.parquet")), (
        "fetch_today_running must not write any cache files"
    )

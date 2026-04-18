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
        arrays.append(
            rng.integers(1_000_000, 5_000_000, size=days).astype(np.int64)
        )
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
    captured: dict[str, object] = {}

    def fake_download(**kwargs: object) -> pd.DataFrame:
        captured.update(kwargs)
        return _bulk_frame(["SPY", "AAPL"])

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)

    source = YFinanceSource(cache_dir=tmp_path)
    out = await source.bulk_download(["spy", "aapl"], period="2y")

    assert captured["threads"] is False
    assert captured["auto_adjust"] is True
    assert captured["progress"] is False
    assert captured["group_by"] == "ticker"
    assert captured["period"] == "2y"
    assert captured["tickers"] == "AAPL SPY"

    assert set(out.keys()) == {"AAPL", "SPY"}
    for frame in out.values():
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.tz is not None


@pytest.mark.asyncio
async def test_bulk_download_populates_parquet_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = {"n": 0}

    def fake_download(**_kwargs: object) -> pd.DataFrame:
        call_count["n"] += 1
        return _bulk_frame(["SPY"])

    monkeypatch.setattr("app.datasources.yfinance_source.yf.download", fake_download)
    source = YFinanceSource(cache_dir=tmp_path)

    await source.bulk_download(["SPY"], period="1y")
    await source.bulk_download(["SPY"], period="1y")

    assert call_count["n"] == 1, "cache hit should avoid second network call"
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

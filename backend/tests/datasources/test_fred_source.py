"""FREDSource — mocked fredapi roundtrip + health."""

from __future__ import annotations

import pandas as pd
import pytest

from app.datasources.fred_source import DEFAULT_SERIES_IDS, FREDSource
from app.security.exceptions import DataSourceError


class _FakeFredClient:
    def __init__(self, *, returns: dict[str, pd.Series], raise_for: set[str] | None = None) -> None:
        self.returns = returns
        self.raise_for = raise_for or set()
        self.calls: list[str] = []

    def get_series(self, series_id: str) -> pd.Series:
        self.calls.append(series_id)
        if series_id in self.raise_for:
            raise ConnectionError("fred down")
        return self.returns.get(series_id, pd.Series(dtype=float))


def test_fred_source_rejects_missing_api_key() -> None:
    with pytest.raises(DataSourceError):
        FREDSource(api_key="")


@pytest.mark.asyncio
async def test_bulk_download_returns_per_series_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2026-01-01", periods=5, freq="B")
    series = pd.Series([3.5, 3.6, 3.7, 3.8, 3.9], index=dates)
    fake = _FakeFredClient(returns={"DGS10": series, "FEDFUNDS": series})

    monkeypatch.setattr("app.datasources.fred_source.Fred", lambda api_key: fake)

    source = FREDSource(api_key="secret")
    out = await source.bulk_download(["DGS10", "FEDFUNDS"])

    assert set(out.keys()) == {"DGS10", "FEDFUNDS"}
    for frame in out.values():
        assert list(frame.columns) == ["value"]
        assert len(frame) == 5


@pytest.mark.asyncio
async def test_bulk_download_gracefully_handles_per_series_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series = pd.Series([1.0, 2.0], index=pd.date_range("2026-01-01", periods=2))
    fake = _FakeFredClient(returns={"DGS10": series}, raise_for={"FEDFUNDS"})
    monkeypatch.setattr("app.datasources.fred_source.Fred", lambda api_key: fake)
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)

    source = FREDSource(api_key="secret")
    out = await source.bulk_download(["DGS10", "FEDFUNDS"])
    assert not out["DGS10"].empty
    assert out["FEDFUNDS"].empty


@pytest.mark.asyncio
async def test_health_check_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    series = pd.Series([4.0], index=pd.to_datetime(["2026-04-01"]))
    fake = _FakeFredClient(returns={"DGS10": series})
    monkeypatch.setattr("app.datasources.fred_source.Fred", lambda api_key: fake)
    source = FREDSource(api_key="secret")
    health = await source.health_check()
    assert health.status == "ok"


def test_default_series_list_is_stable() -> None:
    # Contract used by daily_ingestion + tests. Changing this list is a
    # schema-level change — the failure pushes us to update callers.
    assert DEFAULT_SERIES_IDS == ("DGS10", "DGS2", "DTWEXBGS", "FEDFUNDS", "VIXCLS")

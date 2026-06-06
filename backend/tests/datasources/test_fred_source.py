"""FREDSource — mocked fredapi roundtrip + health."""

from __future__ import annotations

import pandas as pd
import pytest

from app.datasources.fred_source import DEFAULT_SERIES_IDS, FREDSource
from app.security.exceptions import DataSourceError


class _FakeFredClient:
    def __init__(
        self,
        *,
        returns: dict[str, pd.Series],
        raise_for: set[str] | None = None,
        rate_limit_for: dict[str, int] | None = None,
    ) -> None:
        self.returns = returns
        self.raise_for = raise_for or set()
        # Per-series count of how many times to raise "Too Many Requests"
        # before returning a valid frame — used to assert the retry
        # behaviour around FRED's rate limit.
        self.rate_limit_for = dict(rate_limit_for or {})
        self.calls: list[str] = []

    def get_series(self, series_id: str) -> pd.Series:
        self.calls.append(series_id)
        if series_id in self.raise_for:
            raise ConnectionError("fred down")
        remaining = self.rate_limit_for.get(series_id, 0)
        if remaining > 0:
            self.rate_limit_for[series_id] = remaining - 1
            raise ValueError("Too Many Requests.  Exceeded Rate Limit")
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
    # tenacity stores ``sleep`` on the Retrying instance at decoration
    # time, so patching the module-level ``tenacity.nap.sleep`` does
    # nothing once the decorator has run. Reach into the actual
    # Retrying instance attached to the decorated function instead.
    from app.datasources.fred_source import _fetch_with_retry as _fwr

    monkeypatch.setattr(_fwr.retry, "sleep", lambda _s: None)

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
    assert DEFAULT_SERIES_IDS == (
        "DGS10",
        "DGS2",
        "DTWEXBGS",
        "FEDFUNDS",
        "VIXCLS",
        # v2 Phase 4: VIX 3-month (term-structure compare).
        "VXVCLS",
    )


@pytest.mark.asyncio
async def test_bulk_download_retries_through_fred_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real-world reproducer: parallel first-install backfill fires all 5
    series at once, FRED returns 429 on a few of them, and the retry must
    swallow the transient ``ValueError`` so the second attempt succeeds.
    Before the fix, only network errors retried — 429s leaked through
    and left series empty until the next daily_update."""
    series = pd.Series([1.0, 2.0], index=pd.date_range("2026-01-01", periods=2))
    fake = _FakeFredClient(
        returns={"DGS10": series, "DGS2": series, "FEDFUNDS": series},
        # FEDFUNDS gets rate-limited twice, then succeeds. DGS2 gets
        # rate-limited once. Both must end up with data.
        rate_limit_for={"FEDFUNDS": 2, "DGS2": 1},
    )
    monkeypatch.setattr("app.datasources.fred_source.Fred", lambda api_key: fake)
    # tenacity stores ``sleep`` on the Retrying instance at decoration
    # time, so patching the module-level ``tenacity.nap.sleep`` does
    # nothing once the decorator has run. Reach into the actual
    # Retrying instance attached to the decorated function instead.
    from app.datasources.fred_source import _fetch_with_retry as _fwr

    monkeypatch.setattr(_fwr.retry, "sleep", lambda _s: None)

    source = FREDSource(api_key="secret")
    out = await source.bulk_download(["DGS10", "DGS2", "FEDFUNDS"])

    assert not out["DGS10"].empty
    assert not out["DGS2"].empty
    assert not out["FEDFUNDS"].empty
    # FEDFUNDS: 2 rate-limit raises + 1 successful = 3 calls.
    assert fake.calls.count("FEDFUNDS") == 3
    assert fake.calls.count("DGS2") == 2


@pytest.mark.asyncio
async def test_bulk_download_gives_up_after_five_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If FRED stays rate-limited the whole window, eventually we
    surface the failure as an empty frame (graceful degradation)."""
    fake = _FakeFredClient(
        returns={"DGS10": pd.Series(dtype=float)},
        rate_limit_for={"DGS10": 99},
    )
    monkeypatch.setattr("app.datasources.fred_source.Fred", lambda api_key: fake)
    # tenacity stores ``sleep`` on the Retrying instance at decoration
    # time, so patching the module-level ``tenacity.nap.sleep`` does
    # nothing once the decorator has run. Reach into the actual
    # Retrying instance attached to the decorated function instead.
    from app.datasources.fred_source import _fetch_with_retry as _fwr

    monkeypatch.setattr(_fwr.retry, "sleep", lambda _s: None)

    source = FREDSource(api_key="secret")
    out = await source.bulk_download(["DGS10"])

    assert out["DGS10"].empty
    # Bounded to 5 attempts so we don't spin forever.
    assert fake.calls.count("DGS10") == 5

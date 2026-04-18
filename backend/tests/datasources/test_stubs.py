"""Schwab + Polygon stubs raise NotImplementedError on data methods."""

from __future__ import annotations

import pytest

from app.datasources.polygon_source import PolygonSource
from app.datasources.schwab_source import SchwabSource


@pytest.mark.asyncio
async def test_schwab_stub_raises_on_bulk_download() -> None:
    source = SchwabSource()
    with pytest.raises(NotImplementedError):
        await source.bulk_download(["SPY"])


@pytest.mark.asyncio
async def test_schwab_stub_raises_on_get_index_data() -> None:
    source = SchwabSource()
    with pytest.raises(NotImplementedError):
        await source.get_index_data("SPY")


@pytest.mark.asyncio
async def test_schwab_stub_health_is_not_configured() -> None:
    source = SchwabSource()
    health = await source.health_check()
    assert health.status == "not_configured"


@pytest.mark.asyncio
async def test_polygon_stub_raises_on_bulk_download() -> None:
    source = PolygonSource()
    with pytest.raises(NotImplementedError):
        await source.bulk_download(["SPY"])


@pytest.mark.asyncio
async def test_polygon_stub_raises_on_get_index_data() -> None:
    source = PolygonSource()
    with pytest.raises(NotImplementedError):
        await source.get_index_data("SPY")


@pytest.mark.asyncio
async def test_polygon_stub_health_is_not_configured() -> None:
    source = PolygonSource()
    health = await source.health_check()
    assert health.status == "not_configured"

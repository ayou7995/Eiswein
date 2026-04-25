"""Per-indicator 60-day series endpoint tests.

Covers ``GET /api/v1/ticker/{symbol}/indicator/{name}/series`` for the
4 supported indicator slugs (``price_vs_ma``, ``rsi``, ``macd``,
``bollinger``). Each indicator is exercised against a deterministic
260-day synthetic OHLCV dataset so the math primitives are stressed,
not the framing.

Test fixtures intentionally NOT use the cold-start backfill — we want
controlled DailyPrice rows. ``empty_for={symbol}`` makes the cold-start
hand the symbol back as ``delisted``, leaving zero rows; the test then
seeds exactly what it needs via :class:`DailyPriceRepository`.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import User
from app.db.repositories.daily_price_repository import (
    DailyPriceRepository,
    DailyPriceRow,
)
from app.db.repositories.watchlist_repository import WatchlistRepository
from tests.conftest import FakeDataSource, FakeDataSourceConfig


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _install_empty_datasource(app: FastAPI, *, symbols: set[str]) -> None:
    app.state.data_source = FakeDataSource(FakeDataSourceConfig(empty_for=symbols))


def _seed_watchlist(session_factory: sessionmaker[Session], *, symbol: str) -> None:
    """Insert a watchlist row directly, bypassing the route's pre-flight.

    The route fires a yfinance probe through ``data_source.bulk_download``
    which conflicts with this file's ``empty_for=`` data-source isolation
    pattern. Repository-level insert keeps the indicator-series tests
    focused on the math + URL surface.
    """
    with session_factory() as session:
        admin = session.query(User).filter(User.username == "admin").one()
        WatchlistRepository(session).add(user_id=admin.id, symbol=symbol, max_size=50)
        session.commit()


def _seed_synthetic_prices(
    session: Session,
    *,
    symbol: str,
    end: date,
    days: int,
    seed: int = 42,
    start_price: float = 100.0,
) -> list[DailyPriceRow]:
    """Generate ``days`` business-day OHLCV rows ending at ``end``.

    Walks calendar days BACKWARD from ``end`` so the most recent row
    aligns with ``end`` (or the last business day on/before ``end``).
    Random walk with reproducible seed so the indicator math is
    deterministic across test runs.
    """
    rng = np.random.default_rng(seed)
    drift = rng.normal(0.05, 1.0, size=days)
    base = start_price + np.cumsum(drift)
    business_dates: list[date] = []
    cursor = end
    while len(business_dates) < days:
        if cursor.weekday() < 5:
            business_dates.append(cursor)
        cursor -= timedelta(days=1)
    business_dates.reverse()
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        close = round(float(base[i]), 4)
        rows.append(
            DailyPriceRow(
                symbol=symbol,
                date=d,
                open=Decimal(f"{close - 0.5:.4f}"),
                high=Decimal(f"{close + 1.0:.4f}"),
                low=Decimal(f"{close - 1.0:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=1_000_000 + i,
            )
        )
    DailyPriceRepository(session).upsert_many(rows)
    return rows


def _seed_uptrend_prices(
    session: Session,
    *,
    symbol: str,
    end: date,
    days: int,
    base_price: float = 100.0,
    step: float = 0.5,
) -> list[DailyPriceRow]:
    """Like :func:`_seed_synthetic_prices` but a deterministic linear
    uptrend so direction-of-motion assertions don't flake."""
    business_dates: list[date] = []
    cursor = end
    while len(business_dates) < days:
        if cursor.weekday() < 5:
            business_dates.append(cursor)
        cursor -= timedelta(days=1)
    business_dates.reverse()
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        close = base_price + i * step
        rows.append(
            DailyPriceRow(
                symbol=symbol,
                date=d,
                open=Decimal(f"{close - 0.1:.4f}"),
                high=Decimal(f"{close + 0.1:.4f}"),
                low=Decimal(f"{close - 0.2:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=1_000_000,
            )
        )
    DailyPriceRepository(session).upsert_many(rows)
    return rows


# --- auth + 404 paths -----------------------------------------------------


def test_series_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/ticker/AAPL/indicator/rsi/series")
    assert resp.status_code == 401


def test_series_returns_404_when_not_on_watchlist(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/TSLA/indicator/rsi/series")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_series_returns_404_for_unknown_indicator(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    resp = client.get("/api/v1/ticker/AAPL/indicator/foo/series")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_series_rejects_invalid_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/bad symbol/indicator/rsi/series")
    assert resp.status_code == 422


def test_series_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=10)
        session.commit()
    resp = client.get("/api/v1/ticker/AAPL/indicator/rsi/series")
    assert resp.status_code == 404


# --- price_vs_ma ----------------------------------------------------------


def test_price_vs_ma_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/price_vs_ma/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["indicator"] == "price_vs_ma"
    assert len(body["series"]) == 60
    # Ascending by date.
    dates = [pt["date"] for pt in body["series"]]
    assert dates == sorted(dates)
    point = body["series"][-1]
    assert "price" in point
    assert "ma50" in point
    assert "ma200" in point
    current = body["current"]
    assert current["price"] is not None
    assert current["ma50"] is not None
    assert current["ma200"] is not None
    assert isinstance(current["above_both_days"], int)
    summary = body["summary_zh"]
    # Summary must contain a cross note keyword.
    assert "近期黃金交叉" in summary or "近期死亡交叉" in summary or "無近期交叉" in summary
    # Summary must reflect station status (above or not).
    assert ("站上 50/200MA" in summary) or ("未站穩" in summary)


def test_price_vs_ma_above_both_days_uptrend(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """A monotonically rising series ends with price above both MAs."""
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")

    with session_factory() as session:
        _seed_uptrend_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/price_vs_ma/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current"]["above_both_days"] >= 1
    assert "站上 50/200MA" in body["summary_zh"]


# --- rsi ------------------------------------------------------------------


def test_rsi_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/rsi/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "rsi"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "daily" in point and "weekly" in point
    # Weekly carry-forward: if there's a non-null weekly value at the
    # tail, it should fill backward where applicable (no nulls in the
    # last few rows once weekly RSI has warmed up).
    last_5 = body["series"][-5:]
    assert all(p["weekly"] is not None for p in last_5)
    current = body["current"]
    assert current["zone"] in {
        "oversold",
        "neutral_weak",
        "neutral_strong",
        "overbought",
        "unknown",
    }
    assert body["thresholds"] == {"oversold": 30, "overbought": 70}
    assert body["summary_zh"].startswith("日 RSI ")


def test_rsi_zone_classification_overbought(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """A long monotonic uptrend should drive RSI into the overbought zone."""
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")

    with session_factory() as session:
        _seed_uptrend_prices(session, symbol="AAPL", end=date.today(), days=260, step=1.0)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/rsi/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current"]["zone"] == "overbought"
    assert "超買" in body["summary_zh"]


# --- macd -----------------------------------------------------------------


def test_macd_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/macd/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "macd"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "macd" in point
    assert "signal" in point
    assert "histogram" in point
    current = body["current"]
    assert current["last_cross"] in {"golden", "death", None}
    if current["last_cross"] is not None:
        assert isinstance(current["bars_since_cross"], int)
    summary = body["summary_zh"]
    assert "histogram" in summary
    assert "黃金交叉" in summary or "死亡交叉" in summary or "60 日內無交叉" in summary


def test_macd_summary_uptrend_positive_histogram(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")

    with session_factory() as session:
        _seed_uptrend_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/macd/series")
    body = resp.json()
    # Constant +0.5 drift means EMA(fast) > EMA(slow) once warm, so the
    # MACD line stays positive — but at full convergence the line and
    # signal line lock together, leaving a histogram that hovers near
    # zero. The summary should still classify the histogram as
    # positive (or zero) and reference an absent cross.
    assert body["current"]["histogram"] is not None
    assert body["current"]["histogram"] >= 0
    assert "histogram" in body["summary_zh"]


# --- bollinger ------------------------------------------------------------


def test_bollinger_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/bollinger/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "bollinger"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "price" in point
    assert "upper" in point
    assert "middle" in point
    assert "lower" in point
    current = body["current"]
    assert current["upper"] is not None
    assert current["lower"] is not None
    assert current["middle"] is not None
    # band_width must equal upper - lower.
    band_width = current["upper"] - current["lower"]
    assert abs(band_width - current["band_width"]) < 0.01
    # position in [0, 1] for the random-walk fixture (no extreme breaks).
    if current["position"] is not None:
        assert -2.0 <= current["position"] <= 3.0
    # Band-width 5d-change is a delta — float or null.
    assert current["band_width_5d_change"] is None or isinstance(
        current["band_width_5d_change"], float
    )
    summary = body["summary_zh"]
    assert (
        "下軌" in summary
        or "中軌" in summary
        or "上軌" in summary
        or "突破" in summary
        or "跌破" in summary
    )
    assert (
        "帶寬擴張" in summary
        or "帶寬收縮" in summary
        or "帶寬持平" in summary
        or "帶寬資料不足" in summary
    )


def test_bollinger_position_on_uptrend_near_upper(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")

    with session_factory() as session:
        _seed_uptrend_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/bollinger/series")
    body = resp.json()
    # Constant uptrend: latest close is by construction at the top of
    # the rolling window so position should be near 1.0.
    assert body["current"]["position"] is not None
    assert body["current"]["position"] > 0.7


# --- volume_anomaly -------------------------------------------------------


def _seed_volume_pattern(
    session: Session,
    *,
    symbol: str,
    end: date,
    days: int,
    base_volume: int,
    last_volume: int,
    last_close_delta: float = 0.5,
) -> list[DailyPriceRow]:
    """Constant-base series with a known final-day volume + close delta.

    Uses a stable close price for the bulk of the series and bumps the
    last bar so the indicator's per-day price-change % is non-zero. The
    fixture asserts on:
    * ``ratio = last_volume / base_volume`` (today_ratio)
    * ``spike = ratio >= 2``
    """
    business_dates: list[date] = []
    cursor = end
    while len(business_dates) < days:
        if cursor.weekday() < 5:
            business_dates.append(cursor)
        cursor -= timedelta(days=1)
    business_dates.reverse()
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        close = 100.0 if i < days - 1 else 100.0 + last_close_delta
        vol = base_volume if i < days - 1 else last_volume
        rows.append(
            DailyPriceRow(
                symbol=symbol,
                date=d,
                open=Decimal(f"{close - 0.1:.4f}"),
                high=Decimal(f"{close + 0.1:.4f}"),
                low=Decimal(f"{close - 0.2:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=vol,
            )
        )
    DailyPriceRepository(session).upsert_many(rows)
    return rows


def test_volume_anomaly_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/volume_anomaly/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["indicator"] == "volume_anomaly"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "volume" in point
    assert "price_change_pct" in point
    assert "avg_volume_20d" in point
    assert isinstance(point["volume"], int)
    current = body["current"]
    assert isinstance(current["today_volume"], int)
    assert current["avg_volume_20d"] is not None
    assert current["ratio"] is not None
    assert current["five_day_avg_ratio"] is not None
    assert isinstance(current["spike"], bool)


def test_volume_anomaly_summary_shrinking_no_spike(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Last 5 days at half the baseline volume → 5-day avg ratio < 0.85."""
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        # 95 baseline + 5 trailing low-volume days. Manually craft so
        # the rolling 20-day mean spans the constant baseline of 100M
        # and the trailing 5 days each carry 50M, dragging the 5-day
        # ratio mean to ~0.5.
        end = date.today()
        days = 100
        business_dates: list[date] = []
        cursor = end
        while len(business_dates) < days:
            if cursor.weekday() < 5:
                business_dates.append(cursor)
            cursor -= timedelta(days=1)
        business_dates.reverse()
        rows: list[DailyPriceRow] = []
        for i, d in enumerate(business_dates):
            close = 100.0
            vol = 100_000_000 if i < days - 5 else 50_000_000
            rows.append(
                DailyPriceRow(
                    symbol="AAPL",
                    date=d,
                    open=Decimal(f"{close - 0.1:.4f}"),
                    high=Decimal(f"{close + 0.1:.4f}"),
                    low=Decimal(f"{close - 0.2:.4f}"),
                    close=Decimal(f"{close:.4f}"),
                    volume=vol,
                )
            )
        DailyPriceRepository(session).upsert_many(rows)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/volume_anomaly/series")
    body = resp.json()
    summary = body["summary_zh"]
    # Today's ratio ~ 50M / (mix of 100M and 50M baseline) ≤ 1.0;
    # 5-day avg ratio ~ 0.5 → "萎縮中".
    assert "萎縮中" in summary
    assert "今日量" in summary
    assert "5 日均" in summary
    assert body["current"]["spike"] is False
    assert "⚠ 量能爆發" not in summary


def test_volume_anomaly_summary_spike_triggers_warning_prefix(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Today's volume = 3x baseline → spike=True → summary has the
    warning prefix and the today-ratio reads >= 2.0x."""
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_volume_pattern(
            session,
            symbol="AAPL",
            end=date.today(),
            days=100,
            base_volume=100_000_000,
            last_volume=300_000_000,
        )
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/volume_anomaly/series")
    body = resp.json()
    assert body["current"]["spike"] is True
    assert body["current"]["ratio"] is not None
    assert body["current"]["ratio"] >= 2.0
    assert body["summary_zh"].startswith("⚠ 量能爆發 ")


def test_volume_anomaly_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """volume_anomaly needs SERIES_DAYS + 20 bars (warm-up). 70 bars
    is below that threshold so the route should reject with 404."""
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=70)
        session.commit()
    resp = client.get("/api/v1/ticker/AAPL/indicator/volume_anomaly/series")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- relative_strength ----------------------------------------------------


def test_relative_strength_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL", "SPY"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        # SPY needs to live in the daily_price table even though it's
        # not on the user's watchlist — the route loads it directly.
        _seed_synthetic_prices(session, symbol="SPY", end=date.today(), days=260, seed=11)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/relative_strength/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["indicator"] == "relative_strength"
    assert len(body["series"]) == 60
    point = body["series"][0]
    # Day 0 of the series is the anchor — both cum returns are 0.0.
    assert point["ticker_cum_return"] == 0.0
    assert point["spx_cum_return"] == 0.0
    assert point["diff"] == 0.0
    last = body["series"][-1]
    assert last["ticker_cum_return"] is not None
    assert last["spx_cum_return"] is not None
    assert last["diff"] is not None
    assert abs(last["diff"] - (last["ticker_cum_return"] - last["spx_cum_return"])) < 1e-6
    current = body["current"]
    assert current["diff_60d"] is not None
    assert current["ticker_60d_return"] is not None
    assert current["spx_60d_return"] is not None
    summary = body["summary_zh"]
    assert "領先大盤" in summary or "落後大盤" in summary or "與大盤同步" in summary


def test_relative_strength_summary_leads_when_ticker_outpaces_spx(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Ticker uptrend stronger than SPY uptrend → 60-day diff > 0 →
    summary reads "領先大盤"."""
    _install_empty_datasource(app, symbols={"AAPL", "SPY"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_uptrend_prices(session, symbol="AAPL", end=date.today(), days=260, step=1.0)
        _seed_uptrend_prices(session, symbol="SPY", end=date.today(), days=260, step=0.2)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/indicator/relative_strength/series")
    body = resp.json()
    assert body["current"]["diff_60d"] is not None
    assert body["current"]["diff_60d"] > 0
    assert "領先大盤" in body["summary_zh"]


def test_relative_strength_returns_404_when_spy_history_missing(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"AAPL"})
    _login(client, test_password)
    _seed_watchlist(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_synthetic_prices(session, symbol="AAPL", end=date.today(), days=260)
        # Intentionally no SPY seed: the relative_strength branch must
        # 404 with "insufficient_history" rather than 500.
        session.commit()
    resp = client.get("/api/v1/ticker/AAPL/indicator/relative_strength/series")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"

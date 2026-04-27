"""Per-indicator 60-day market-series endpoint tests.

Covers ``GET /api/v1/market/indicator/{name}/series`` for the 4 supported
indicator slugs (``spx_ma``, ``vix``, ``yield_spread``, ``ad_day``). Each
indicator is exercised against deterministic fixture data so the math
primitives are stressed, not the framing.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.daily_price_repository import (
    DailyPriceRepository,
    DailyPriceRow,
)
from app.db.repositories.macro_repository import MacroRepository, MacroRow
from tests.conftest import FakeDataSource, FakeDataSourceConfig


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _install_empty_datasource(app: FastAPI, *, symbols: set[str]) -> None:
    app.state.data_source = FakeDataSource(FakeDataSourceConfig(empty_for=symbols))


def _business_dates_ending(*, end: date, days: int) -> list[date]:
    """Return ``days`` business-day dates ending at or before ``end``."""
    out: list[date] = []
    cursor = end
    while len(out) < days:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor -= timedelta(days=1)
    out.reverse()
    return out


def _seed_synthetic_spy(
    session: Session,
    *,
    end: date,
    days: int,
    seed: int = 42,
    start_price: float = 500.0,
    base_volume: int = 80_000_000,
) -> list[DailyPriceRow]:
    """Random-walk OHLCV seeded for SPY. Volume jitters around ``base_volume``
    so the A/D Day classification has both up-volume and down-volume bars.
    """
    rng = np.random.default_rng(seed)
    drift = rng.normal(0.05, 1.5, size=days)
    base = start_price + np.cumsum(drift)
    vol_jitter = rng.normal(0, 0.15, size=days)
    business_dates = _business_dates_ending(end=end, days=days)
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        close = round(float(base[i]), 4)
        # Stagger open vs close so up/down day classification flips
        # naturally — alternating sign patterns based on the noise.
        open_offset = 0.6 if (i + d.toordinal()) % 2 == 0 else -0.6
        open_price = round(close - open_offset, 4)
        rows.append(
            DailyPriceRow(
                symbol="SPY",
                date=d,
                open=Decimal(f"{open_price:.4f}"),
                high=Decimal(f"{max(open_price, close) + 1.0:.4f}"),
                low=Decimal(f"{min(open_price, close) - 1.0:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=int(base_volume * (1.0 + vol_jitter[i])),
            )
        )
    DailyPriceRepository(session).upsert_many(rows)
    return rows


def _seed_uptrend_spy(
    session: Session,
    *,
    end: date,
    days: int,
    base_price: float = 400.0,
    step: float = 0.5,
) -> list[DailyPriceRow]:
    business_dates = _business_dates_ending(end=end, days=days)
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        close = base_price + i * step
        # Uptrend: every bar closes above its open so direction is up.
        # Volume alternates ±10% so volume_expanding flips bar-to-bar.
        open_price = close - 0.2
        vol = 90_000_000 if i % 2 == 0 else 70_000_000
        rows.append(
            DailyPriceRow(
                symbol="SPY",
                date=d,
                open=Decimal(f"{open_price:.4f}"),
                high=Decimal(f"{close + 0.1:.4f}"),
                low=Decimal(f"{open_price - 0.2:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=vol,
            )
        )
    DailyPriceRepository(session).upsert_many(rows)
    return rows


def _seed_macro_series(
    session: Session,
    *,
    series_id: str,
    end: date,
    days: int,
    values: list[float],
) -> list[MacroRow]:
    """Seed FRED-style macro rows for the given series.

    ``values`` must have length ``days``; the test caller controls the
    series shape. We use calendar days backward from ``end`` (FRED has
    daily-cadence series for VIXCLS / DGS10 / DGS2 — weekend gaps in the
    real data are filled with the prior day, so calendar days are fine
    for the fixture).
    """
    assert len(values) == days, "values length must match days"
    out: list[MacroRow] = []
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        out.append(
            MacroRow(
                series_id=series_id,
                date=d,
                value=Decimal(f"{values[i]:.6f}"),
            )
        )
    MacroRepository(session).upsert_many(out)
    return out


# --- auth + 404 paths -----------------------------------------------------


def test_market_series_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/market/indicator/vix/series")
    assert resp.status_code == 401


def test_market_series_returns_404_for_unknown_indicator(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/market/indicator/foo/series")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_spx_ma_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_synthetic_spy(session, end=date.today(), days=10)
        session.commit()
    resp = client.get("/api/v1/market/indicator/spx_ma/series")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_vix_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="VIXCLS",
            end=date.today(),
            days=10,
            values=[18.0] * 10,
        )
        session.commit()
    resp = client.get("/api/v1/market/indicator/vix/series")
    assert resp.status_code == 404


def test_yield_spread_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="DGS10",
            end=date.today(),
            days=10,
            values=[4.25] * 10,
        )
        _seed_macro_series(
            session,
            series_id="DGS2",
            end=date.today(),
            days=10,
            values=[3.80] * 10,
        )
        session.commit()
    resp = client.get("/api/v1/market/indicator/yield_spread/series")
    assert resp.status_code == 404


def test_ad_day_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_synthetic_spy(session, end=date.today(), days=20)
        session.commit()
    resp = client.get("/api/v1/market/indicator/ad_day/series")
    assert resp.status_code == 404


# --- spx_ma ---------------------------------------------------------------


def test_spx_ma_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_synthetic_spy(session, end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/market/indicator/spx_ma/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "spx_ma"
    assert len(body["series"]) == 60
    dates = [pt["date"] for pt in body["series"]]
    assert dates == sorted(dates)
    point = body["series"][-1]
    assert "price" in point and "ma50" in point and "ma200" in point
    current = body["current"]
    assert current["price"] is not None
    assert current["ma50"] is not None
    assert current["ma200"] is not None
    assert isinstance(current["above_both_days"], int)
    summary = body["summary_zh"]
    # Summary must reference cross status in either form.
    assert (
        "近期黃金交叉" in summary or "近期死亡交叉" in summary or "無近期黃金/死亡交叉" in summary
    )
    assert ("SPX 站上雙均" in summary) or ("SPX 未站穩" in summary)


def test_spx_ma_above_both_days_uptrend(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_uptrend_spy(session, end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/market/indicator/spx_ma/series")
    body = resp.json()
    assert body["current"]["above_both_days"] >= 1
    assert "SPX 站上雙均" in body["summary_zh"]


# --- vix ------------------------------------------------------------------


def test_vix_series_shape_normal_zone(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    # 300 calendar days of VIX with light noise around 18 (normal zone).
    rng = np.random.default_rng(7)
    values = (18.0 + rng.normal(0, 0.5, size=300)).tolist()
    with session_factory() as session:
        _seed_macro_series(session, series_id="VIXCLS", end=end, days=300, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/vix/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "vix"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "level" in point
    current = body["current"]
    assert current["level"] is not None
    assert current["zone"] in {"low", "normal", "elevated", "panic"}
    # Normal zone for ~18 +/- noise.
    assert current["zone"] == "normal"
    assert 0.0 <= current["percentile_1y"] <= 1.0
    assert body["thresholds"] == {"low": 12, "normal_high": 20, "elevated_high": 30}
    assert "正常區" in body["summary_zh"]
    assert "百分位" in body["summary_zh"]


def test_vix_series_panic_zone_with_rising_trend(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    # 300 days. Steady at 20, then ramp up sharply over the last 15 days
    # to land at ~35 (panic zone, rising more than 2 points over 10d).
    base = [20.0] * 285
    ramp = [20.0 + i for i in range(1, 16)]
    values = base + ramp
    with session_factory() as session:
        _seed_macro_series(session, series_id="VIXCLS", end=end, days=300, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/vix/series")
    body = resp.json()
    assert body["current"]["zone"] == "panic"
    assert body["current"]["trend"] == "rising"
    assert body["current"]["ten_day_change"] > 2.0
    assert "10 日上升" in body["summary_zh"]
    assert "恐慌區" in body["summary_zh"]


def test_vix_series_falling_trend_appended_to_summary(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    # 300 days. Steady at 30, then drop sharply over the last 15 days
    # to land at 15 — falling more than 2 points; zone ends at "normal".
    base = [30.0] * 285
    drop = [30.0 - i for i in range(1, 16)]
    values = base + drop
    with session_factory() as session:
        _seed_macro_series(session, series_id="VIXCLS", end=end, days=300, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/vix/series")
    body = resp.json()
    assert body["current"]["trend"] == "falling"
    assert body["current"]["ten_day_change"] < -2.0
    assert "10 日下降" in body["summary_zh"]


# --- yield_spread ---------------------------------------------------------


def test_yield_spread_series_shape_positive_spread(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    # 300 days, 10y at 4.30, 2y at 3.79 → spread ~0.51 (positive, never inverted).
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="DGS10",
            end=end,
            days=300,
            values=[4.30] * 300,
        )
        _seed_macro_series(
            session,
            series_id="DGS2",
            end=end,
            days=300,
            values=[3.79] * 300,
        )
        session.commit()

    resp = client.get("/api/v1/market/indicator/yield_spread/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "yield_spread"
    # yield_spread defaults to a 1-year (252 trading day) window so the
    # inversion → recovery cycle (typically 1-2 years) fits on screen.
    assert len(body["series"]) == 252
    point = body["series"][-1]
    assert "spread" in point and "ten_year" in point and "two_year" in point
    current = body["current"]
    assert current["spread"] is not None
    assert current["spread"] > 0
    assert current["days_since_inversion"] is None
    assert current["last_inversion_end"] is None
    assert "正斜率" in body["summary_zh"]
    assert "無近期倒掛" in body["summary_zh"]


def test_yield_spread_currently_inverted(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    # 10y < 2y for entire window — currently inverted.
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="DGS10",
            end=end,
            days=300,
            values=[3.80] * 300,
        )
        _seed_macro_series(
            session,
            series_id="DGS2",
            end=end,
            days=300,
            values=[4.30] * 300,
        )
        session.commit()

    resp = client.get("/api/v1/market/indicator/yield_spread/series")
    body = resp.json()
    assert body["current"]["spread"] < 0
    assert body["current"]["days_since_inversion"] == 0
    assert "倒掛" in body["summary_zh"]
    assert "警示" in body["summary_zh"]


def test_yield_spread_recently_uninverted(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """First half of the 60-day window inverted, second half positive.

    Walks the spread from -0.20 to +0.30 across 300 calendar days; the
    most recent inverted day is guaranteed to be inside the trailing
    60-day window.
    """
    _login(client, test_password)
    end = date.today()
    # Linear ramp: 10y - 2y goes from -0.20 to +0.30 over 300 days. The
    # last 60 days span roughly the +0.20 → +0.30 portion, so the cross
    # back to positive lives ~120 days from end → outside the 60-day
    # output but the per-row spread is positive across the tail. To keep
    # an inversion inside the tail, we instead use a slow ramp that
    # crosses zero ~30 days before end.
    ten = [4.0 + (i * 0.001) for i in range(300)]  # 4.00 → 4.299
    # 2y is constant at 4.20: spread = ten - 4.20, crosses zero around
    # ten == 4.20 → i == 200. So days 0..199 inverted, days 200..299
    # positive. The 60-day tail starts at day 240 → spread ~ +0.04 to
    # +0.099, no inversion in tail. Adjust 2y so the cross lands ~30
    # days from the end: choose 2y = 4.27 → cross at ten == 4.27 → i == 270.
    # Tail = days 240..299; days 240..269 inverted (ten 4.24..4.269 < 4.27),
    # days 270..299 positive.
    two = [4.27] * 300
    with session_factory() as session:
        _seed_macro_series(session, series_id="DGS10", end=end, days=300, values=ten)
        _seed_macro_series(session, series_id="DGS2", end=end, days=300, values=two)
        session.commit()

    resp = client.get("/api/v1/market/indicator/yield_spread/series")
    body = resp.json()
    assert body["current"]["spread"] > 0
    days_since = body["current"]["days_since_inversion"]
    assert days_since is not None
    assert 0 < days_since < 60
    assert body["current"]["last_inversion_end"] is not None
    assert "正斜率" in body["summary_zh"]
    assert "脫離倒掛" in body["summary_zh"]


# --- ad_day ---------------------------------------------------------------


def test_ad_day_series_shape(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_synthetic_spy(session, end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/market/indicator/ad_day/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "ad_day"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert point["classification"] in {"accum", "distrib", "neutral"}
    assert isinstance(point["spx_change"], float | type(None))
    assert isinstance(point["volume_ratio"], float | type(None))
    current = body["current"]
    # Counts must add up to ≤ window length and never negative.
    for k in (
        "accum_count_25d",
        "distrib_count_25d",
        "accum_count_5d",
        "distrib_count_5d",
    ):
        assert isinstance(current[k], int)
        assert current[k] >= 0
    assert current["accum_count_25d"] + current["distrib_count_25d"] <= 25
    assert current["accum_count_5d"] + current["distrib_count_5d"] <= 5
    assert current["net_25d"] == current["accum_count_25d"] - current["distrib_count_25d"]
    assert current["net_5d"] == current["accum_count_5d"] - current["distrib_count_5d"]
    assert "過去 25 天累積/出貨" in body["summary_zh"]


def test_ad_day_uptrend_alternating_volume_classifies_accum(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Uptrend with alternating ±10% volume produces accum on volume-up
    bars only (every other bar), distrib never (every bar is up-day),
    and neutral on volume-down bars."""
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    with session_factory() as session:
        _seed_uptrend_spy(session, end=date.today(), days=260)
        session.commit()

    resp = client.get("/api/v1/market/indicator/ad_day/series")
    body = resp.json()
    classes = [pt["classification"] for pt in body["series"]]
    # No down days in the uptrend fixture → no distribution.
    assert "distrib" not in classes
    # Roughly half are accum (volume-up + price-up); rest neutral.
    assert classes.count("accum") > 0
    assert classes.count("neutral") > 0
    assert body["current"]["distrib_count_25d"] == 0
    assert body["current"]["net_25d"] >= 0
    assert "累積" in body["summary_zh"]


def test_ad_day_summary_appends_5d_modifier_when_diverging(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """A 25-day window with mixed classifications + a strongly accumulating
    last-5-day stretch must surface the divergence in the summary string.
    """
    _install_empty_datasource(app, symbols={"SPY"})
    _login(client, test_password)
    end = date.today()
    days = 100
    business_dates = _business_dates_ending(end=end, days=days)
    rows: list[DailyPriceRow] = []
    for i, d in enumerate(business_dates):
        # Days in [days-7, days-2] are strong accumulation: up day with
        # increasing volume. Earlier days are noisy / mixed (alternating
        # neutral / distrib so net_25d ≤ +1).
        if i >= days - 7:
            open_price = 100.0
            close = 102.0
            vol = 100_000_000 + (i - (days - 7)) * 10_000_000  # strictly increasing
        elif i % 3 == 0:
            open_price = 100.0
            close = 98.0
            vol = 90_000_000
        else:
            open_price = 100.0
            close = 100.5
            vol = 80_000_000  # constant: volume never expands → neutral
        rows.append(
            DailyPriceRow(
                symbol="SPY",
                date=d,
                open=Decimal(f"{open_price:.4f}"),
                high=Decimal(f"{max(open_price, close) + 1.0:.4f}"),
                low=Decimal(f"{min(open_price, close) - 1.0:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=vol,
            )
        )
    with session_factory() as session:
        DailyPriceRepository(session).upsert_many(rows)
        session.commit()

    resp = client.get("/api/v1/market/indicator/ad_day/series")
    body = resp.json()
    summary = body["summary_zh"]
    # 25-day window leans neutral or output of mixed signals; 5-day window
    # must read as 累積 because the last 5 bars are all up + volume rising.
    current = body["current"]
    assert current["accum_count_5d"] >= 4
    # Divergence triggers the appended phrase only when 25d != 5d label.
    if abs(current["net_25d"]) <= 1 and current["net_5d"] > 1:
        assert "最近 5 天" in summary
        assert "累積" in summary


# --- dxy ------------------------------------------------------------------


def test_dxy_returns_404_when_history_too_short(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="DTWEXBGS",
            end=date.today(),
            days=10,
            values=[120.0] * 10,
        )
        session.commit()
    resp = client.get("/api/v1/market/indicator/dxy/series")
    assert resp.status_code == 404


def test_dxy_series_shape(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    rng = np.random.default_rng(13)
    values = (120.0 + rng.normal(0, 0.3, size=200)).tolist()
    with session_factory() as session:
        _seed_macro_series(session, series_id="DTWEXBGS", end=end, days=200, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/dxy/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "dxy"
    assert len(body["series"]) == 60
    point = body["series"][-1]
    assert "level" in point and "ma20" in point
    current = body["current"]
    assert current["level"] is not None
    assert current["ma20"] is not None
    assert isinstance(current["streak_rising"], bool)
    assert isinstance(current["streak_falling"], bool)
    assert isinstance(current["streak_days"], int)
    assert current["ma20_change_5d"] is not None
    summary = body["summary_zh"]
    assert "DXY 走弱" in summary or "DXY 走強" in summary or "DXY 持平" in summary
    # Detail clause always references 5-day change.
    assert "5 日變化" in summary


def test_dxy_falling_streak_summary_says_weakening(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """A monotonically declining series produces a falling MA20 streak
    of >= 5 → summary leads with '走弱'."""
    _login(client, test_password)
    end = date.today()
    # 200-day linear decline; MA20 will fall every day once warm.
    values = [125.0 - (i * 0.05) for i in range(200)]
    with session_factory() as session:
        _seed_macro_series(session, series_id="DTWEXBGS", end=end, days=200, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/dxy/series")
    body = resp.json()
    assert body["current"]["streak_falling"] is True
    assert body["current"]["streak_days"] >= 5
    assert body["current"]["ma20_change_5d"] is not None
    assert body["current"]["ma20_change_5d"] < 0
    assert "DXY 走弱" in body["summary_zh"]
    assert "MA20 連跌" in body["summary_zh"]


def test_dxy_rising_streak_summary_says_strengthening(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    end = date.today()
    values = [110.0 + (i * 0.05) for i in range(200)]
    with session_factory() as session:
        _seed_macro_series(session, series_id="DTWEXBGS", end=end, days=200, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/dxy/series")
    body = resp.json()
    assert body["current"]["streak_rising"] is True
    assert "DXY 走強" in body["summary_zh"]
    assert "MA20 連升" in body["summary_zh"]


# --- fed_rate -------------------------------------------------------------


def test_fed_rate_returns_404_when_no_history(
    client: TestClient,
    test_password: str,
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/market/indicator/fed_rate/series")
    assert resp.status_code == 404


def test_fed_rate_series_shape_flat_year(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Constant 5.25% all year → series has 365 rows, delta_30d == 0,
    summary tells the user how long it has been at this level (which
    matches the FED_FUNDS_30D_WINDOW fallback path)."""
    _login(client, test_password)
    end = date.today()
    with session_factory() as session:
        _seed_macro_series(
            session,
            series_id="FEDFUNDS",
            end=end,
            days=365,
            values=[5.25] * 365,
        )
        session.commit()

    resp = client.get("/api/v1/market/indicator/fed_rate/series")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicator"] == "fed_rate"
    # 365-day step chart contract.
    assert len(body["series"]) == 365
    point = body["series"][-1]
    assert "rate" in point
    assert point["rate"] is not None
    current = body["current"]
    assert current["current_rate"] is not None
    assert abs(current["current_rate"] - 5.25) < 1e-6
    assert current["delta_30d"] == 0
    # Flat for the entire window → no detected last change.
    assert current["last_change_direction"] is None
    assert current["days_since_last_change"] is None
    assert current["last_change_date"] is None
    assert body["summary_zh"].startswith("Fed 利率 5.25%")


def test_fed_rate_summary_holding_after_cut(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Last change inside the window was a cut > 30 days ago → summary
    reads 'Fed 利率 X%, 已持平 N 天 (上次降息 YYYY-MM-DD)'."""
    _login(client, test_password)
    end = date.today()
    days = 365
    # First 274 days at 4.50, last 91 days at 4.25 (rate cut ~91 days ago).
    cut_idx = 274
    values = [4.50] * cut_idx + [4.25] * (days - cut_idx)
    with session_factory() as session:
        _seed_macro_series(session, series_id="FEDFUNDS", end=end, days=days, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/fed_rate/series")
    body = resp.json()
    current = body["current"]
    assert abs(current["current_rate"] - 4.25) < 1e-6
    # Held flat for >= 30 days at the new level → delta_30d == 0.
    assert current["delta_30d"] == 0
    assert current["last_change_direction"] == "cut"
    assert current["days_since_last_change"] is not None
    assert current["days_since_last_change"] > 30
    assert current["last_change_date"] is not None
    summary = body["summary_zh"]
    assert summary.startswith("Fed 利率 4.25%")
    assert "已持平" in summary
    assert "上次降息" in summary


def test_fed_rate_summary_active_cut_within_30d(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Rate cut inside the trailing 30-day window → delta_30d != 0 →
    summary reads 'Fed 利率 X%, 30 日內降息 0.25%'."""
    _login(client, test_password)
    end = date.today()
    days = 365
    cut_idx = days - 10
    values = [5.50] * cut_idx + [5.25] * (days - cut_idx)
    with session_factory() as session:
        _seed_macro_series(session, series_id="FEDFUNDS", end=end, days=days, values=values)
        session.commit()

    resp = client.get("/api/v1/market/indicator/fed_rate/series")
    body = resp.json()
    current = body["current"]
    assert current["delta_30d"] is not None
    assert current["delta_30d"] < 0
    assert "30 日內降息" in body["summary_zh"]

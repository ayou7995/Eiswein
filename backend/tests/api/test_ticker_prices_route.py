"""Ticker price-history endpoint tests.

Covers the full surface of ``GET /api/v1/ticker/{symbol}/prices``:
auth, watchlist ownership scoping, ordering, range enforcement, the
``ALL`` 5-year cap, and the intentional empty-list-vs-404 distinction
between "symbol not on watchlist" and "no price rows stored yet".

These tests seed :class:`DailyPrice` rows directly via the repository
rather than letting the cold-start backfill run. ``POST /watchlist``
hands the symbol to the cold-start pipeline which, under the default
FakeDataSource, injects ~60 synthetic rows of its own — that would
overwrite or collide with the controlled fixtures we need here. Using
``empty_for={symbol}`` makes cold-start finish with ``data_status=
delisted`` and zero price rows, giving each test a blank slate.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Watchlist
from app.db.repositories.daily_price_repository import (
    DailyPriceRepository,
    DailyPriceRow,
)
from tests.conftest import FakeDataSource, FakeDataSourceConfig


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _install_empty_datasource(app: FastAPI, *, symbols: set[str]) -> None:
    """Swap in a FakeDataSource that treats ``symbols`` as empty.

    Phase 1 UX overhaul note: ``POST /watchlist`` now pre-flights the
    symbol via this DataSource, so ``empty_for={X}`` makes the symbol
    invalid from the API's perspective. These tests therefore bypass
    the POST route entirely by inserting Watchlist rows directly — see
    :func:`_seed_watchlist_row`.
    """
    app.state.data_source = FakeDataSource(FakeDataSourceConfig(empty_for=symbols))


def _seed_watchlist_row(
    session_factory: sessionmaker[Session],
    *,
    symbol: str,
    user_id: int = 1,
) -> None:
    """Insert a watchlist row directly so these tests can exercise the
    price-history endpoint without running the onboarding pipeline.
    """
    with session_factory() as session:
        existing = session.query(Watchlist).filter_by(user_id=user_id, symbol=symbol).one_or_none()
        if existing is None:
            session.add(Watchlist(user_id=user_id, symbol=symbol, data_status="ready"))
            session.commit()


def _seed_prices(
    session: Session,
    *,
    symbol: str,
    end: date,
    days: int,
) -> None:
    """Insert ``days`` consecutive calendar-day OHLCV rows ending at ``end``.

    Calendar-day cadence (not business-day) keeps the arithmetic in the
    test obvious — if a test asks for 30 days, it gets 30 rows.
    """
    rows: list[DailyPriceRow] = []
    for offset in range(days):
        row_date = end - timedelta(days=days - 1 - offset)
        # Price scales with offset so ordering bugs would show up as
        # non-monotonic close values.
        close = Decimal(f"{100 + offset}.1234")
        rows.append(
            DailyPriceRow(
                symbol=symbol,
                date=row_date,
                open=close - Decimal("0.5000"),
                high=close + Decimal("1.0000"),
                low=close - Decimal("1.0000"),
                close=close,
                volume=1_000_000 + offset,
            )
        )
    DailyPriceRepository(session).upsert_many(rows)


def test_prices_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/ticker/AAPL/prices")
    assert resp.status_code == 401


def test_prices_returns_404_when_not_on_watchlist(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/TSLA/prices")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_prices_rejects_invalid_symbol(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/ticker/bad symbol/prices")
    assert resp.status_code == 422


def test_prices_rejects_invalid_range(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    _seed_watchlist_row(session_factory, symbol="AAPL")
    resp = client.get("/api/v1/ticker/AAPL/prices?range=2W")
    assert resp.status_code == 422


def test_prices_empty_when_no_rows_stored(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """A watchlist row with no DailyPrice rows yet returns an empty list,
    NOT 404 — the chart UI distinguishes "loading" from "not found"."""
    _login(client, test_password)
    _seed_watchlist_row(session_factory, symbol="AAPL")
    resp = client.get("/api/v1/ticker/AAPL/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["range"] == "6M"
    assert body["timezone"] == "America/New_York"
    assert body["bars"] == []


def test_prices_returns_bars_ascending_by_date(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    _seed_watchlist_row(session_factory, symbol="AAPL")
    with session_factory() as session:
        _seed_prices(session, symbol="AAPL", end=date.today(), days=10)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/prices?range=1M")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["range"] == "1M"
    assert len(body["bars"]) == 10
    # Ascending order (TradingView requires monotonically increasing time).
    dates = [bar["date"] for bar in body["bars"]]
    assert dates == sorted(dates)
    # Numeric fields serialized as JSON numbers (not quoted Decimal strings).
    first_bar = body["bars"][0]
    assert isinstance(first_bar["open"], float)
    assert isinstance(first_bar["high"], float)
    assert isinstance(first_bar["low"], float)
    assert isinstance(first_bar["close"], float)
    assert isinstance(first_bar["volume"], int)


def test_prices_range_1m_excludes_older_rows(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    _login(client, test_password)
    _seed_watchlist_row(session_factory, symbol="AAPL")
    today = date.today()
    with session_factory() as session:
        # 120 calendar days — well past the 1M (≈30d) window.
        _seed_prices(session, symbol="AAPL", end=today, days=120)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/prices?range=1M")
    assert resp.status_code == 200
    bars = resp.json()["bars"]
    # 1 month back from today → roughly 28-31 days depending on month
    # length. Assert the window boundary rather than an exact count.
    cutoff = today - timedelta(days=31)
    assert all(date.fromisoformat(bar["date"]) >= cutoff for bar in bars)
    assert len(bars) <= 32  # 30 or 31 days + today
    assert len(bars) >= 27


def test_prices_all_capped_to_five_years(
    client: TestClient,
    test_password: str,
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """``ALL`` is bounded server-side so a user with 8 years of stored
    history can't blow up the chart renderer or JSON payload."""
    _login(client, test_password)
    _seed_watchlist_row(session_factory, symbol="AAPL")
    today = date.today()
    with session_factory() as session:
        # 8 full years of daily rows (calendar-day spacing).
        _seed_prices(session, symbol="AAPL", end=today, days=365 * 8)
        session.commit()

    resp = client.get("/api/v1/ticker/AAPL/prices?range=ALL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "ALL"
    bars = body["bars"]
    oldest = date.fromisoformat(bars[0]["date"])
    # relativedelta(years=5) lands on the same month/day five years ago;
    # allow a small tolerance for leap-year / month-end snapping.
    five_years_ago = today - timedelta(days=365 * 5 + 2)
    assert oldest >= five_years_ago
    # Six-year-old rows must NOT be present.
    six_years_ago = today - timedelta(days=365 * 6)
    assert oldest > six_years_ago


def test_prices_scoped_to_requesting_user(
    client: TestClient,
    test_password: str,
    session_factory: sessionmaker[Session],
) -> None:
    """Symbols on *another* user's watchlist must 404 even if DailyPrice
    rows exist (prices are global by symbol but exposure is gated on
    watchlist ownership, matching the indicators/signal endpoints)."""
    _login(client, test_password)
    # Seed prices for a symbol the logged-in user never added.
    with session_factory() as session:
        _seed_prices(session, symbol="NVDA", end=date.today(), days=5)
        session.commit()

    resp = client.get("/api/v1/ticker/NVDA/prices")
    assert resp.status_code == 404

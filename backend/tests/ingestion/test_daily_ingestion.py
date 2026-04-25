"""daily_update — ONE bulk call, market calendar, graceful degradation, gap-aware flow."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import User, Watchlist
from app.db.repositories.daily_price_repository import DailyPriceRepository
from app.db.repositories.watchlist_repository import WatchlistRepository
from app.ingestion.daily_ingestion import (
    _ComputeOutcome,
    _oldest_gap,
    _period_for_window,
    run_daily_update,
)


def _seed_watchlist(
    session_factory: sessionmaker[Session], per_user_symbols: dict[str, list[str]]
) -> None:
    with session_factory() as session:
        for username, symbols in per_user_symbols.items():
            user = User(username=username, password_hash="x")
            session.add(user)
            session.flush()
            for sym in symbols:
                session.add(Watchlist(user_id=user.id, symbol=sym, data_status="pending"))
        session.commit()


@pytest.mark.asyncio
async def test_daily_update_issues_exactly_one_bulk_call(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    _seed_watchlist(
        session_factory,
        {"u1": ["SPY", "QQQ"], "u2": ["SPY", "IWM"]},
    )

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    # distinct_symbols_across_users deduplicates SPY
    assert result.market_open is True
    assert result.symbols_requested == 3
    assert result.symbols_succeeded == 3
    assert result.symbols_failed == 0
    # Exactly one bulk fetch for all 3 distinct symbols
    assert len(fake_data_source.calls) == 1  # type: ignore[attr-defined]
    assert fake_data_source.calls[0][0] == "bulk"  # type: ignore[attr-defined]
    assert sorted(fake_data_source.calls[0][1]) == ["IWM", "QQQ", "SPY"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_daily_update_pins_spy_even_when_no_user_has_it(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPY must be in the fetch set even if no user's watchlist has it.

    The system benchmark drives several regime + relative-strength
    indicators; fetching its prices is mandatory. SYSTEM_SYMBOLS unions
    into ``distinct_symbols_across_users()`` inside run_daily_update.
    """
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    # Seed only non-SPY symbols across users.
    _seed_watchlist(session_factory, {"u1": ["AAPL", "QQQ"]})

    with session_factory() as session:
        await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    # Bulk_download call must include SPY via the SYSTEM_SYMBOLS pin.
    assert len(fake_data_source.calls) == 1  # type: ignore[attr-defined]
    fetched_symbols = set(fake_data_source.calls[0][1])  # type: ignore[attr-defined]
    assert "SPY" in fetched_symbols
    assert "AAPL" in fetched_symbols
    assert "QQQ" in fetched_symbols


@pytest.mark.asyncio
async def test_daily_update_skips_on_non_trading_day(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: False)
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
        )

    assert result.market_open is False
    assert result.symbols_requested == 0
    assert fake_data_source.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_daily_update_isolates_per_symbol_failures(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import FakeDataSource, FakeDataSourceConfig, _make_price_frame

    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)

    ds = FakeDataSource(
        FakeDataSourceConfig(
            frames={
                "SPY": _make_price_frame(),
                "QQQ": _make_price_frame(),
            },
            empty_for={"DELIST"},
        )
    )
    _seed_watchlist(session_factory, {"u1": ["SPY", "QQQ", "DELIST"]})

    with session_factory() as session:
        result = await run_daily_update(db=session, data_source=ds, settings=settings)

    assert result.symbols_requested == 3
    assert result.symbols_succeeded == 2
    assert result.symbols_delisted == 1
    assert result.symbols_failed == 0

    with session_factory() as session:
        prices = DailyPriceRepository(session)
        assert prices.count_for_symbol("SPY") > 0
        assert prices.count_for_symbol("QQQ") > 0
        assert prices.count_for_symbol("DELIST") == 0
        wl = WatchlistRepository(session)
        row = wl.get(user_id=1, symbol="DELIST")
        assert row is not None
        assert row.data_status == "delisted"


@pytest.mark.asyncio
async def test_daily_update_is_idempotent(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    with session_factory() as session:
        first = await run_daily_update(
            db=session,
            data_source=fake_data_source,
            settings=settings,  # type: ignore[arg-type]
        )
        first_rows = DailyPriceRepository(session).count_for_symbol("SPY")

    with session_factory() as session:
        second = await run_daily_update(
            db=session,
            data_source=fake_data_source,
            settings=settings,  # type: ignore[arg-type]
        )
        second_rows = DailyPriceRepository(session).count_for_symbol("SPY")

    assert first.symbols_succeeded == 1
    # UPSERT: same dates → same row count (idempotent). This is the
    # load-bearing idempotency assertion — re-running daily_update
    # never duplicates DailyPrice rows.
    assert first_rows == second_rows
    # Gap-aware refresh (Workstream B): on the second run every date
    # the FakeDataSource can supply is already present, so no rows
    # are written the second time regardless of succeeded/failed
    # accounting (which now depends on whether the upstream covers
    # the remaining gap set).
    assert second.price_rows_upserted == 0
    assert second.gaps_filled_rows == 0


# ---------------------------------------------------------------------------
# Helpers shared by the gap-aware tests below
# ---------------------------------------------------------------------------


def _stub_compute_outcome() -> _ComputeOutcome:
    """No-op compute outcome so gap tests don't need real indicator data."""
    from app.signals.types import MarketPosture

    return _ComputeOutcome(
        indicators_ok=0,
        indicators_failed=0,
        snapshots_ok=0,
        snapshots_failed=0,
        market_posture=MarketPosture.NORMAL,
    )


# ---------------------------------------------------------------------------
# Workstream B — gap-aware refresh (trigger modes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_update_manual_no_gaps_still_calls_bulk_download(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual trigger with zero gaps must still call bulk_download once.

    The UX invariant: clicking 立即更新 is never a silent no-op — we
    always try to fetch the last trading day.
    """
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion._compute_and_compose_for_all",
        lambda **_kw: _stub_compute_outcome(),
    )
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    # Patch find_gaps_for_symbols so no gaps are reported.
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.DailyPriceRepository.find_gaps_for_symbols",
        lambda self, syms, **_kw: {s.upper(): [] for s in syms},
    )

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
            trigger="manual",
        )

    assert result.market_open is True
    # No gaps were present → gap counters stay zero.
    assert result.gaps_filled_rows == 0
    assert result.gaps_filled_symbols == 0
    # BUT bulk_download must still have been called once (manual trigger).
    assert len(fake_data_source.calls) == 1  # type: ignore[attr-defined]
    assert fake_data_source.calls[0][0] == "bulk"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_daily_update_scheduled_no_gaps_skips_bulk_download(
    session_factory: sessionmaker[Session],
    fake_data_source: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduled trigger with zero gaps must NOT call bulk_download.

    The nightly job has already fetched everything — yfinance must be
    spared the redundant call.
    """
    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion._compute_and_compose_for_all",
        lambda **_kw: _stub_compute_outcome(),
    )
    _seed_watchlist(session_factory, {"u1": ["SPY"]})

    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.DailyPriceRepository.find_gaps_for_symbols",
        lambda self, syms, **_kw: {s.upper(): [] for s in syms},
    )

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=fake_data_source,  # type: ignore[arg-type]
            settings=settings,
            trigger="scheduled",
        )

    assert result.market_open is True
    # Scheduled + no gaps → short-circuit, no yfinance call.
    assert fake_data_source.calls == []  # type: ignore[attr-defined]
    assert result.gaps_filled_rows == 0
    assert result.gaps_filled_symbols == 0


@pytest.mark.asyncio
async def test_daily_update_gaps_in_two_symbols_fills_all(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gaps in SPY (3 dates) + QQQ (1 date) → 4 rows filled, 2 symbols filled.

    _oldest_gap must select min(d1, d4) as the fetch start so the bulk
    window covers both gap sets. Only the gap dates get UPSERTed.
    """
    from tests.conftest import FakeDataSource, FakeDataSourceConfig

    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion._compute_and_compose_for_all",
        lambda **_kw: _stub_compute_outcome(),
    )

    # Four distinct trading days in the past; all are Mondays/Tuesdays so
    # they're definitely trading days.
    d1 = date(2026, 3, 2)
    d2 = date(2026, 3, 3)
    d3 = date(2026, 3, 4)
    d4 = date(2026, 3, 9)  # later than d1–d3 for QQQ

    spy_gaps = [d1, d2, d3]
    qqq_gaps = [d4]

    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.DailyPriceRepository.find_gaps_for_symbols",
        lambda self, syms, **_kw: {
            "SPY": spy_gaps if "SPY" in [s.upper() for s in syms] else [],
            "QQQ": qqq_gaps if "QQQ" in [s.upper() for s in syms] else [],
        },
    )

    _seed_watchlist(session_factory, {"u1": ["SPY", "QQQ"]})

    ds = FakeDataSource(FakeDataSourceConfig())

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=ds,
            settings=settings,
            trigger="scheduled",
        )

    # Exactly one bulk call.
    assert len(ds.calls) == 1
    assert ds.calls[0][0] == "bulk"

    # The fetch window must cover d1 (oldest gap) — the period string
    # should reflect a span from d1 to session_day.
    assert result.gaps_filled_symbols == 2
    assert result.gaps_filled_rows == 4


@pytest.mark.asyncio
async def test_daily_update_partial_yfinance_failure_fills_other_symbol(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When yfinance returns empty for one symbol, the other still gets filled.

    Graceful degradation: one symbol's failure must not abort the whole run.
    """
    from tests.conftest import FakeDataSource, FakeDataSourceConfig, _make_price_frame

    monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
    monkeypatch.setattr(
        "app.ingestion.daily_ingestion._compute_and_compose_for_all",
        lambda **_kw: _stub_compute_outcome(),
    )

    d1 = date(2026, 3, 2)

    monkeypatch.setattr(
        "app.ingestion.daily_ingestion.DailyPriceRepository.find_gaps_for_symbols",
        lambda self, syms, **_kw: {
            "SPY": [d1] if "SPY" in [s.upper() for s in syms] else [],
            "FAIL": [d1] if "FAIL" in [s.upper() for s in syms] else [],
        },
    )

    _seed_watchlist(session_factory, {"u1": ["SPY", "FAIL"]})

    # FAIL returns empty frame (simulates a delisted / bad symbol).
    ds = FakeDataSource(
        FakeDataSourceConfig(
            frames={"SPY": _make_price_frame()},
            empty_for={"FAIL"},
        )
    )

    with session_factory() as session:
        result = await run_daily_update(
            db=session,
            data_source=ds,
            settings=settings,
            trigger="scheduled",
        )

    # SPY gap got filled; FAIL was delisted.
    assert result.symbols_delisted == 1
    with session_factory() as session:
        prices = DailyPriceRepository(session)
        assert prices.count_for_symbol("SPY") > 0
        assert prices.count_for_symbol("FAIL") == 0


# ---------------------------------------------------------------------------
# Unit tests for pure helper functions
# ---------------------------------------------------------------------------


def test_oldest_gap_returns_minimum_date() -> None:
    gaps = {
        "SPY": [date(2026, 3, 5), date(2026, 3, 6)],
        "QQQ": [date(2026, 3, 2), date(2026, 3, 3)],
        "IWM": [],
    }
    assert _oldest_gap(gaps) == date(2026, 3, 2)


def test_oldest_gap_all_empty_falls_back_gracefully() -> None:
    # When all gap lists are empty, _oldest_gap should not crash.
    result = _oldest_gap({"SPY": [], "QQQ": []})
    # Should return a date (last_trading_day_et fallback) without raising.
    assert isinstance(result, date)


def test_period_for_window_same_day_floors_at_5d() -> None:
    p = _period_for_window(start_date=date(2026, 4, 20), end_date=date(2026, 4, 20))
    # span_days=1, buffered=1+5=6 → but floor is 5, so: max(6,5)=6 → "6d"
    assert p == "6d"


def test_period_for_window_multi_day_span() -> None:
    # 10 calendar days apart + 5 buffer = 16 days.
    p = _period_for_window(start_date=date(2026, 4, 1), end_date=date(2026, 4, 11))
    span = (date(2026, 4, 11) - date(2026, 4, 1)).days + 1  # 11
    expected = max(span + 5, 5)
    assert p == f"{expected}d"

"""PositionRepository — CRUD, weighted-average cost, partial unique."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.position_repository import (
    InsufficientSharesError,
    OpenPositionExistsError,
    PositionHasRemainingSharesError,
    PositionRepository,
)


def _mk_user(session: Session, username: str) -> int:
    user = User(username=username, password_hash="x", is_admin=False)
    session.add(user)
    session.flush()
    return user.id


def _open_at(year: int = 2026, month: int = 1, day: int = 2) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_create_and_fetch(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    position = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("10"),
        avg_cost=Decimal("500.0000"),
        opened_at=_open_at(),
    )
    fetched = repo.get_by_id(user_id=uid, position_id=position.id)
    assert fetched is not None
    assert fetched.symbol == "SPY"
    assert fetched.shares == Decimal("10")
    assert fetched.avg_cost == Decimal("500.0000")


def test_create_refuses_duplicate_open(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("1"),
        opened_at=_open_at(),
    )
    with pytest.raises(OpenPositionExistsError):
        repo.create_open(
            user_id=uid,
            symbol="spy",  # case-insensitive
            shares=Decimal("2"),
            avg_cost=Decimal("2"),
            opened_at=_open_at(),
        )


def test_cross_user_isolation(db_session: Session) -> None:
    alice = _mk_user(db_session, "alice")
    bob = _mk_user(db_session, "bob")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=alice,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("1"),
        opened_at=_open_at(),
    )
    assert repo.get_by_id(user_id=bob, position_id=p.id) is None
    assert repo.get_by_id(user_id=alice, position_id=p.id) is not None


def test_apply_buy_weighted_average(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("10"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    # 10 @ 100 + 5 @ 120 => 15 @ (1000 + 600) / 15 = 1600/15
    repo.apply_buy(p, shares=Decimal("5"), price=Decimal("120"))
    assert p.shares == Decimal("15")
    # Keep generous precision — no float comparison.
    expected = (Decimal("1000") + Decimal("600")) / Decimal("15")
    assert p.avg_cost == expected

    # A third add to double-check: + 5 @ 80 => 20 @ (15 * expected + 5*80)/20
    repo.apply_buy(p, shares=Decimal("5"), price=Decimal("80"))
    assert p.shares == Decimal("20")
    expected_2 = (Decimal("15") * expected + Decimal("5") * Decimal("80")) / Decimal("20")
    assert p.avg_cost == expected_2


def test_apply_sell_computes_realized_pnl(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("10"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    realized = repo.apply_sell(p, shares=Decimal("4"), price=Decimal("120"))
    # (120 - 100) * 4 = 80
    assert realized == Decimal("80")
    assert p.shares == Decimal("6")
    assert p.avg_cost == Decimal("100")  # preserved on partial sell
    assert p.closed_at is None


def test_apply_sell_auto_closes_on_zero(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("3"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    repo.apply_sell(p, shares=Decimal("3"), price=Decimal("150"))
    assert p.shares == Decimal("0")
    assert p.closed_at is not None


def test_apply_sell_refuses_over_reduce(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("2"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    with pytest.raises(InsufficientSharesError):
        repo.apply_sell(p, shares=Decimal("3"), price=Decimal("120"))


def test_close_if_empty_requires_zero_shares(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    p = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    with pytest.raises(PositionHasRemainingSharesError):
        repo.close_if_empty(p)


def test_reopen_after_close(db_session: Session) -> None:
    """Partial unique index must allow a new OPEN after previous closed."""
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    first = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("100"),
        opened_at=_open_at(),
    )
    repo.apply_sell(first, shares=Decimal("1"), price=Decimal("110"))
    assert first.closed_at is not None

    second = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("2"),
        avg_cost=Decimal("120"),
        opened_at=_open_at(2026, 2, 1),
    )
    assert second.id != first.id
    assert second.closed_at is None


def test_list_open_vs_all(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = PositionRepository(db_session)
    a = repo.create_open(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("10"),
        opened_at=_open_at(),
    )
    repo.apply_sell(a, shares=Decimal("1"), price=Decimal("15"))
    repo.create_open(
        user_id=uid,
        symbol="QQQ",
        shares=Decimal("2"),
        avg_cost=Decimal("20"),
        opened_at=_open_at(),
    )
    assert len(repo.list_open_for_user(uid)) == 1
    assert len(repo.list_all_for_user(uid)) == 2
    assert repo.count_for_user(uid) == 1  # open only
    assert repo.count_for_user(uid, include_closed=True) == 2


def test_partial_unique_db_level(db_session: Session) -> None:
    """Defense-in-depth: even if the repo check is bypassed, the DB
    partial-unique index refuses a duplicate open row.

    The test engine fixture uses ``Base.metadata.create_all`` which
    does NOT apply the partial-unique index (SQLAlchemy has no
    portable declaration for that — it lives in Alembic). We create
    the same index here so the invariant can still be exercised
    without standing up an Alembic harness per test.
    """
    from sqlalchemy import text

    from app.db.models import Position

    db_session.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_user_symbol_open "
            "ON positions (user_id, symbol) WHERE closed_at IS NULL"
        )
    )
    uid = _mk_user(db_session, "alice")
    row_a = Position(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("1"),
        opened_at=_open_at(),
    )
    row_b = Position(
        user_id=uid,
        symbol="SPY",
        shares=Decimal("2"),
        avg_cost=Decimal("2"),
        opened_at=_open_at(),
    )
    db_session.add(row_a)
    db_session.flush()
    db_session.add(row_b)
    with pytest.raises(IntegrityError):
        db_session.flush()

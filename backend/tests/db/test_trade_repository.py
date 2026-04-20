"""TradeRepository — append-only + filters."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.trade_repository import TradeRepository


def _mk_user(session: Session, username: str) -> int:
    user = User(username=username, password_hash="x", is_admin=False)
    session.add(user)
    session.flush()
    return user.id


def _at(day: int = 2) -> datetime:
    return datetime(2026, 1, day, 15, 0, tzinfo=UTC)


def test_append_and_list_for_user(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = TradeRepository(db_session)
    repo.append(
        user_id=uid,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(2),
    )
    repo.append(
        user_id=uid,
        position_id=None,
        symbol="QQQ",
        side="buy",
        shares=Decimal("2"),
        price=Decimal("200"),
        executed_at=_at(3),
    )
    rows = repo.list_for_user(user_id=uid)
    # DESC ordering: QQQ (day 3) before SPY (day 2).
    assert [r.symbol for r in rows] == ["QQQ", "SPY"]


def test_list_filters_by_symbol_and_side(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = TradeRepository(db_session)
    repo.append(
        user_id=uid,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(2),
    )
    repo.append(
        user_id=uid,
        position_id=None,
        symbol="SPY",
        side="sell",
        shares=Decimal("1"),
        price=Decimal("110"),
        executed_at=_at(3),
    )
    rows_sell = repo.list_for_user(user_id=uid, symbol="SPY", side="sell")
    assert len(rows_sell) == 1
    assert rows_sell[0].side == "sell"


def test_list_filters_by_date_range(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = TradeRepository(db_session)
    for day in (2, 3, 4, 5):
        repo.append(
            user_id=uid,
            position_id=None,
            symbol="SPY",
            side="buy",
            shares=Decimal("1"),
            price=Decimal("100"),
            executed_at=_at(day),
        )
    start = date(2026, 1, 3)
    end = date(2026, 1, 4)
    rows = repo.list_for_user(user_id=uid, start_date=start, end_date=end)
    assert len(rows) == 2


def test_user_isolation(db_session: Session) -> None:
    alice = _mk_user(db_session, "alice")
    bob = _mk_user(db_session, "bob")
    repo = TradeRepository(db_session)
    repo.append(
        user_id=alice,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(),
    )
    repo.append(
        user_id=bob,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("99"),
        price=Decimal("100"),
        executed_at=_at(),
    )
    alice_rows = repo.list_for_user(user_id=alice)
    assert len(alice_rows) == 1
    assert alice_rows[0].shares == Decimal("1")


def test_list_for_position_is_user_scoped(db_session: Session) -> None:
    """list_for_position must also filter by user so a guessed
    position_id from another user can't leak trade rows."""
    from app.db.repositories.position_repository import PositionRepository

    alice = _mk_user(db_session, "alice")
    bob = _mk_user(db_session, "bob")
    positions = PositionRepository(db_session)
    trades_repo = TradeRepository(db_session)

    alice_pos = positions.create_open(
        user_id=alice,
        symbol="SPY",
        shares=Decimal("1"),
        avg_cost=Decimal("100"),
        opened_at=_at(),
    )
    # Alice's trade with her own position.
    trades_repo.append(
        user_id=alice,
        position_id=alice_pos.id,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(),
    )
    # Bob shouldn't ever be able to surface alice_pos's trade through
    # the repo's user-scoped method even with a guessed id.
    bob_rows = trades_repo.list_for_position(user_id=bob, position_id=alice_pos.id)
    assert bob_rows == []
    alice_rows = trades_repo.list_for_position(user_id=alice, position_id=alice_pos.id)
    assert len(alice_rows) == 1


def test_count_for_user(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = TradeRepository(db_session)
    assert repo.count_for_user(uid) == 0
    for day in (2, 3):
        repo.append(
            user_id=uid,
            position_id=None,
            symbol="SPY",
            side="buy",
            shares=Decimal("1"),
            price=Decimal("100"),
            executed_at=_at(day),
        )
    assert repo.count_for_user(uid) == 2


def test_append_is_immutable(db_session: Session) -> None:
    """Appending never mutates an existing row — distinct create_at+id."""
    uid = _mk_user(db_session, "alice")
    repo = TradeRepository(db_session)
    first = repo.append(
        user_id=uid,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(2),
    )
    second = repo.append(
        user_id=uid,
        position_id=None,
        symbol="SPY",
        side="buy",
        shares=Decimal("1"),
        price=Decimal("100"),
        executed_at=_at(2),
    )
    assert first.id != second.id
    # Time ordering within same second is allowed — but created_at is
    # non-null and at/after first.created_at.
    assert second.created_at - first.created_at >= timedelta(0)

"""WatchlistGroupRepository — CRUD + ordering + collisions + cap + orphans."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models import User, Watchlist
from app.db.repositories.watchlist_group_repository import (
    MAX_GROUPS_PER_USER,
    DuplicateGroupNameError,
    GroupLimitExceededError,
    WatchlistGroupRepository,
)
from app.security.exceptions import NotFoundError


def _mk_user(session: Session, username: str = "alice") -> int:
    user = User(username=username, password_hash="x", is_admin=False)
    session.add(user)
    session.flush()
    return user.id


def _mk_watchlist(session: Session, user_id: int, symbol: str) -> Watchlist:
    row = Watchlist(user_id=user_id, symbol=symbol, data_status="ready")
    session.add(row)
    session.flush()
    return row


def test_create_assigns_incremental_position(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    a = repo.create(user_id=uid, name="Core holdings")
    b = repo.create(user_id=uid, name="Watching")
    c = repo.create(user_id=uid, name="Speculative")
    assert (a.position, b.position, c.position) == (0, 1, 2)


def test_list_orders_by_position_then_id(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    repo.create(user_id=uid, name="Alpha")
    repo.create(user_id=uid, name="Beta")
    repo.create(user_id=uid, name="Gamma")
    rows = list(repo.list_for_user(uid))
    assert [r.name for r in rows] == ["Alpha", "Beta", "Gamma"]


def test_create_case_insensitive_collision_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    repo.create(user_id=uid, name="Watching")
    with pytest.raises(DuplicateGroupNameError):
        repo.create(user_id=uid, name="WATCHING")
    with pytest.raises(DuplicateGroupNameError):
        repo.create(user_id=uid, name="watching")


def test_create_strips_whitespace(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    row = repo.create(user_id=uid, name="  Trimmed  ")
    assert row.name == "Trimmed"


def test_limit_enforced_at_20(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    for i in range(MAX_GROUPS_PER_USER):
        repo.create(user_id=uid, name=f"Group {i:02d}")
    with pytest.raises(GroupLimitExceededError):
        repo.create(user_id=uid, name="OverflowGroup")


def test_rename_updates_name(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    row = repo.create(user_id=uid, name="Old")
    renamed = repo.rename(user_id=uid, group_id=row.id, new_name="New")
    assert renamed.name == "New"


def test_rename_case_insensitive_collision_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    repo.create(user_id=uid, name="Watching")
    other = repo.create(user_id=uid, name="Speculative")
    with pytest.raises(DuplicateGroupNameError):
        repo.rename(user_id=uid, group_id=other.id, new_name="WATCHING")


def test_rename_to_same_name_is_noop(db_session: Session) -> None:
    """Renaming to the same name (case-insensitive) does not raise."""
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    row = repo.create(user_id=uid, name="Watching")
    renamed = repo.rename(user_id=uid, group_id=row.id, new_name="WATCHING")
    assert renamed.name == "WATCHING"


def test_rename_unknown_group_raises_not_found(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    with pytest.raises(NotFoundError):
        repo.rename(user_id=uid, group_id=999, new_name="X")


def test_reorder_assigns_positions_in_order(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    a = repo.create(user_id=uid, name="A")
    b = repo.create(user_id=uid, name="B")
    c = repo.create(user_id=uid, name="C")
    repo.reorder(user_id=uid, ordered_group_ids=[c.id, a.id, b.id])
    rows = list(repo.list_for_user(uid))
    assert [r.name for r in rows] == ["C", "A", "B"]
    assert [r.position for r in rows] == [0, 1, 2]


def test_reorder_with_unknown_id_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    a = repo.create(user_id=uid, name="A")
    b = repo.create(user_id=uid, name="B")
    with pytest.raises(NotFoundError):
        repo.reorder(user_id=uid, ordered_group_ids=[a.id, b.id, 999])


def test_reorder_with_partial_set_raises(db_session: Session) -> None:
    """All ids must be present — partial reorders aren't allowed."""
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    a = repo.create(user_id=uid, name="A")
    repo.create(user_id=uid, name="B")
    with pytest.raises(NotFoundError):
        repo.reorder(user_id=uid, ordered_group_ids=[a.id])


def test_delete_orphans_member_rows(db_session: Session) -> None:
    """Deleting a group sets ``watchlist.group_id = NULL`` for members."""
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    row = repo.create(user_id=uid, name="Watching")

    wl = _mk_watchlist(db_session, uid, "AAA")
    wl.group_id = row.id
    db_session.flush()

    repo.delete(user_id=uid, group_id=row.id)

    db_session.refresh(wl)
    assert wl.group_id is None
    # Group is physically gone.
    assert repo.get(user_id=uid, group_id=row.id) is None


def test_delete_unknown_raises_not_found(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    with pytest.raises(NotFoundError):
        repo.delete(user_id=uid, group_id=999)


def test_user_isolation(db_session: Session) -> None:
    uid_a = _mk_user(db_session, "alice")
    uid_b = _mk_user(db_session, "bob")
    repo = WatchlistGroupRepository(db_session)
    repo.create(user_id=uid_a, name="Watching")
    # Bob can use the same name independently.
    repo.create(user_id=uid_b, name="Watching")
    assert {g.user_id for g in repo.list_for_user(uid_a)} == {uid_a}
    assert {g.user_id for g in repo.list_for_user(uid_b)} == {uid_b}


def test_count_symbols_per_group(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistGroupRepository(db_session)
    g1 = repo.create(user_id=uid, name="A")
    g2 = repo.create(user_id=uid, name="B")
    wl1 = _mk_watchlist(db_session, uid, "AAA")
    wl1.group_id = g1.id
    wl2 = _mk_watchlist(db_session, uid, "BBB")
    wl2.group_id = g1.id
    wl3 = _mk_watchlist(db_session, uid, "CCC")
    wl3.group_id = g2.id
    db_session.flush()
    counts = repo.count_symbols_per_group(uid)
    assert counts == {g1.id: 2, g2.id: 1}

"""WatchlistRepository — CRUD + UNIQUE + 100 cap."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.watchlist_repository import (
    DuplicateWatchlistEntryError,
    WatchlistFullError,
    WatchlistRepository,
)
from app.security.exceptions import NotFoundError


def _mk_user(session: Session, username: str) -> int:
    user = User(username=username, password_hash="x", is_admin=False)
    session.add(user)
    session.flush()
    return user.id


def test_add_and_list(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid, symbol="SPY", max_size=100)
    repo.add(user_id=uid, symbol="QQQ", max_size=100)
    rows = repo.list_for_user(uid)
    assert [r.symbol for r in rows] == ["SPY", "QQQ"]


def test_add_normalizes_symbol(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid, symbol="spy", max_size=100)
    row = repo.get(user_id=uid, symbol="SPY")
    assert row is not None


def test_add_duplicate_raises(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid, symbol="SPY", max_size=100)
    with pytest.raises(DuplicateWatchlistEntryError):
        repo.add(user_id=uid, symbol="spy", max_size=100)


def test_watchlist_cap_enforced(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    for sym in ("AAA", "BBB", "CCC"):
        repo.add(user_id=uid, symbol=sym, max_size=3)
    with pytest.raises(WatchlistFullError):
        repo.add(user_id=uid, symbol="DDD", max_size=3)


def test_remove_raises_not_found_when_absent(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    with pytest.raises(NotFoundError):
        repo.remove(user_id=uid, symbol="NONEX")


def test_set_status_updates_and_marks_refreshed(db_session: Session) -> None:
    uid = _mk_user(db_session, "alice")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid, symbol="SPY", max_size=100)
    repo.set_status(user_id=uid, symbol="SPY", status="ready", mark_refreshed=True)
    row = repo.get(user_id=uid, symbol="SPY")
    assert row is not None
    assert row.data_status == "ready"
    assert row.last_refresh_at is not None


def test_distinct_symbols_across_users(db_session: Session) -> None:
    uid_a = _mk_user(db_session, "alice")
    uid_b = _mk_user(db_session, "bob")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid_a, symbol="SPY", max_size=100)
    repo.add(user_id=uid_b, symbol="SPY", max_size=100)
    repo.add(user_id=uid_b, symbol="QQQ", max_size=100)
    assert sorted(repo.distinct_symbols_across_users()) == ["QQQ", "SPY"]


def test_list_all_for_symbol_returns_per_user_rows(db_session: Session) -> None:
    uid_a = _mk_user(db_session, "alice")
    uid_b = _mk_user(db_session, "bob")
    repo = WatchlistRepository(db_session)
    repo.add(user_id=uid_a, symbol="SPY", max_size=100)
    repo.add(user_id=uid_b, symbol="SPY", max_size=100)
    rows = repo.list_all_for_symbol("SPY")
    assert len(rows) == 2

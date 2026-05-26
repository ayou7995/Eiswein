"""WatchlistTagRepository — CRUD + attach/detach + popular ranking + caps."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models import User, Watchlist
from app.db.repositories.watchlist_tag_repository import (
    MAX_TAGS_PER_USER,
    DuplicateTagNameError,
    InvalidTagColorError,
    TagLimitExceededError,
    WatchlistTagRepository,
)
from app.security.exceptions import NotFoundError, ValidationError


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


def test_create_and_list_orders_by_name(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    repo.create(user_id=uid, name="Zeta", color="#FF0000")
    repo.create(user_id=uid, name="alpha", color="#00FF00")
    repo.create(user_id=uid, name="Beta", color="#0000FF")
    rows = list(repo.list_for_user(uid))
    assert [r.name for r in rows] == ["alpha", "Beta", "Zeta"]


def test_create_case_insensitive_collision_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    repo.create(user_id=uid, name="AI", color="#22C55E")
    with pytest.raises(DuplicateTagNameError):
        repo.create(user_id=uid, name="ai", color="#22C55E")


def test_create_invalid_color_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    with pytest.raises(InvalidTagColorError):
        repo.create(user_id=uid, name="AI", color="red")
    with pytest.raises(InvalidTagColorError):
        repo.create(user_id=uid, name="AI", color="#FFF")  # 3-digit hex rejected
    with pytest.raises(InvalidTagColorError):
        repo.create(user_id=uid, name="AI", color="#XYZ123")


def test_create_name_too_long_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    with pytest.raises(ValidationError):
        repo.create(user_id=uid, name="x" * 33, color="#FF0000")


def test_limit_enforced_at_30(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    for i in range(MAX_TAGS_PER_USER):
        repo.create(user_id=uid, name=f"tag{i:02d}", color="#FF0000")
    with pytest.raises(TagLimitExceededError):
        repo.create(user_id=uid, name="overflow", color="#FF0000")


def test_rename_happy_path(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    row = repo.create(user_id=uid, name="old", color="#FF0000")
    renamed = repo.rename(user_id=uid, tag_id=row.id, new_name="new")
    assert renamed.name == "new"


def test_rename_collision_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    repo.create(user_id=uid, name="AI", color="#FF0000")
    other = repo.create(user_id=uid, name="Semis", color="#00FF00")
    with pytest.raises(DuplicateTagNameError):
        repo.rename(user_id=uid, tag_id=other.id, new_name="AI")


def test_recolor_happy_path(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    row = repo.create(user_id=uid, name="AI", color="#FF0000")
    recolored = repo.recolor(user_id=uid, tag_id=row.id, new_color="#00FF00")
    assert recolored.color == "#00FF00"


def test_recolor_invalid_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    row = repo.create(user_id=uid, name="AI", color="#FF0000")
    with pytest.raises(InvalidTagColorError):
        repo.recolor(user_id=uid, tag_id=row.id, new_color="not-hex")


def test_delete_removes_tag_and_attachments(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    row = repo.create(user_id=uid, name="AI", color="#FF0000")
    wl = _mk_watchlist(db_session, uid, "AAA")
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=row.id)
    db_session.flush()

    repo.delete(user_id=uid, tag_id=row.id)
    assert repo.get(user_id=uid, tag_id=row.id) is None
    # Attachment cascade-deleted.
    assert list(repo.list_attachments_for_watchlist(wl.id)) == []


def test_delete_unknown_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    with pytest.raises(NotFoundError):
        repo.delete(user_id=uid, tag_id=999)


def test_attach_is_idempotent(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    tag = repo.create(user_id=uid, name="AI", color="#FF0000")
    wl = _mk_watchlist(db_session, uid, "AAA")
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    # Second attach is a no-op (no exception, no duplicate row).
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    assert len(list(repo.list_attachments_for_watchlist(wl.id))) == 1


def test_attach_with_unowned_tag_raises(db_session: Session) -> None:
    uid_a = _mk_user(db_session, "alice")
    uid_b = _mk_user(db_session, "bob")
    repo = WatchlistTagRepository(db_session)
    tag = repo.create(user_id=uid_a, name="AI", color="#FF0000")
    wl = _mk_watchlist(db_session, uid_b, "AAA")
    with pytest.raises(NotFoundError):
        repo.attach(user_id=uid_b, watchlist_id=wl.id, tag_id=tag.id)


def test_attach_with_unowned_watchlist_raises(db_session: Session) -> None:
    uid_a = _mk_user(db_session, "alice")
    uid_b = _mk_user(db_session, "bob")
    repo = WatchlistTagRepository(db_session)
    tag = repo.create(user_id=uid_a, name="AI", color="#FF0000")
    wl = _mk_watchlist(db_session, uid_b, "AAA")
    with pytest.raises(NotFoundError):
        repo.attach(user_id=uid_a, watchlist_id=wl.id, tag_id=tag.id)


def test_detach_is_idempotent(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    tag = repo.create(user_id=uid, name="AI", color="#FF0000")
    wl = _mk_watchlist(db_session, uid, "AAA")
    # Detach a non-attached tag — should be a no-op.
    repo.detach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    # Attach + detach + detach again — still no-op.
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    repo.detach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    repo.detach(user_id=uid, watchlist_id=wl.id, tag_id=tag.id)
    assert list(repo.list_attachments_for_watchlist(wl.id)) == []


def test_list_attachments_for_watchlist(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    tag_a = repo.create(user_id=uid, name="AI", color="#FF0000")
    tag_b = repo.create(user_id=uid, name="Semis", color="#00FF00")
    wl = _mk_watchlist(db_session, uid, "NVDA")
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=tag_a.id)
    repo.attach(user_id=uid, watchlist_id=wl.id, tag_id=tag_b.id)
    rows = list(repo.list_attachments_for_watchlist(wl.id))
    assert {r.name for r in rows} == {"AI", "Semis"}


def test_popular_for_user_ranks_by_attachment_count(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    tag_a = repo.create(user_id=uid, name="AI", color="#FF0000")
    tag_b = repo.create(user_id=uid, name="Semis", color="#00FF00")
    tag_c = repo.create(user_id=uid, name="EV", color="#0000FF")

    wl1 = _mk_watchlist(db_session, uid, "NVDA")
    wl2 = _mk_watchlist(db_session, uid, "TSM")
    wl3 = _mk_watchlist(db_session, uid, "TSLA")
    # AI: 3 attachments  Semis: 2  EV: 1.
    repo.attach(user_id=uid, watchlist_id=wl1.id, tag_id=tag_a.id)
    repo.attach(user_id=uid, watchlist_id=wl2.id, tag_id=tag_a.id)
    repo.attach(user_id=uid, watchlist_id=wl3.id, tag_id=tag_a.id)
    repo.attach(user_id=uid, watchlist_id=wl1.id, tag_id=tag_b.id)
    repo.attach(user_id=uid, watchlist_id=wl2.id, tag_id=tag_b.id)
    repo.attach(user_id=uid, watchlist_id=wl1.id, tag_id=tag_c.id)

    popular = list(repo.popular_for_user(uid))
    assert [t.name for t in popular] == ["AI", "Semis", "EV"]


def test_popular_includes_zero_attachment_tags(db_session: Session) -> None:
    """All tags surface in popular — zero-attachment ones sit at the bottom."""
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    repo.create(user_id=uid, name="A", color="#FF0000")
    repo.create(user_id=uid, name="B", color="#00FF00")
    popular = list(repo.popular_for_user(uid))
    assert {t.name for t in popular} == {"A", "B"}


def test_popular_respects_limit(db_session: Session) -> None:
    uid = _mk_user(db_session)
    repo = WatchlistTagRepository(db_session)
    for i in range(10):
        repo.create(user_id=uid, name=f"tag{i:02d}", color="#FF0000")
    popular = list(repo.popular_for_user(uid, limit=5))
    assert len(popular) == 5

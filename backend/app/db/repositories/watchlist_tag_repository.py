"""Watchlist tag CRUD + attach/detach — user-scoped.

Tag CRUD mirrors the group repository's shape. Attach/detach use the
join table directly so a watchlist row can carry many tags
(many-to-many).

Idempotency story
-----------------
``attach`` uses an existence check before INSERT so a double-attach
returns silently rather than raising IntegrityError. The composite PK
on the join table is still the source of truth — a concurrent INSERT
would surface as IntegrityError; the repository swallows that case too.

``detach`` does a DELETE WHERE; missing rows are a no-op.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Watchlist, WatchlistSymbolTag, WatchlistTag
from app.security.exceptions import EisweinError, NotFoundError

MAX_TAGS_PER_USER = 30

# Same shape as the DB-level CHECK constraint.
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class DuplicateTagNameError(EisweinError):
    http_status = 409
    code = "tag_duplicate_name"
    message = "標籤名稱已存在"


class TagLimitExceededError(EisweinError):
    http_status = 422
    code = "tag_limit_exceeded"
    message = "標籤數量已達上限"


class InvalidTagColorError(EisweinError):
    http_status = 422
    code = "tag_invalid_color"
    message = "標籤顏色格式不合法（必須是 #RRGGBB 形式）"


class WatchlistTagRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------------- tag CRUD ---------------- #

    def list_for_user(self, user_id: int) -> Sequence[WatchlistTag]:
        """Tags sorted by name (case-insensitive) for stable UI listing."""
        stmt = (
            select(WatchlistTag)
            .where(WatchlistTag.user_id == user_id)
            .order_by(func.lower(WatchlistTag.name).asc(), WatchlistTag.id.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def get(self, *, user_id: int, tag_id: int) -> WatchlistTag | None:
        stmt = select(WatchlistTag).where(
            WatchlistTag.user_id == user_id,
            WatchlistTag.id == tag_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, *, user_id: int, name: str, color: str) -> WatchlistTag:
        cleaned_name = _normalize_name(name)
        cleaned_color = _validate_color(color)
        if self._count_for_user(user_id) >= MAX_TAGS_PER_USER:
            raise TagLimitExceededError(details={"max": MAX_TAGS_PER_USER})
        if self._find_by_name(user_id=user_id, name=cleaned_name) is not None:
            raise DuplicateTagNameError(details={"name": cleaned_name})
        row = WatchlistTag(user_id=user_id, name=cleaned_name, color=cleaned_color)
        self._session.add(row)
        self._session.flush()
        return row

    def rename(self, *, user_id: int, tag_id: int, new_name: str) -> WatchlistTag:
        cleaned = _normalize_name(new_name)
        row = self.get(user_id=user_id, tag_id=tag_id)
        if row is None:
            raise NotFoundError(details={"tag_id": tag_id})
        if row.name.lower() != cleaned.lower():
            colliding = self._find_by_name(user_id=user_id, name=cleaned)
            if colliding is not None and colliding.id != row.id:
                raise DuplicateTagNameError(details={"name": cleaned})
        row.name = cleaned
        self._session.flush()
        return row

    def recolor(self, *, user_id: int, tag_id: int, new_color: str) -> WatchlistTag:
        cleaned = _validate_color(new_color)
        row = self.get(user_id=user_id, tag_id=tag_id)
        if row is None:
            raise NotFoundError(details={"tag_id": tag_id})
        row.color = cleaned
        self._session.flush()
        return row

    def delete(self, *, user_id: int, tag_id: int) -> None:
        row = self.get(user_id=user_id, tag_id=tag_id)
        if row is None:
            raise NotFoundError(details={"tag_id": tag_id})
        # CASCADE on watchlist_symbol_tag handles attachment cleanup.
        self._session.delete(row)
        self._session.flush()

    # ---------------- attach / detach ---------------- #

    def attach(self, *, user_id: int, watchlist_id: int, tag_id: int) -> None:
        """Idempotent attach of ``tag_id`` to ``watchlist_id``.

        Both ids must belong to ``user_id`` — raises NotFoundError if
        either is missing or owned by another user. Re-attaching the
        same tag is a no-op.
        """
        self._assert_ownership(
            user_id=user_id, watchlist_id=watchlist_id, tag_id=tag_id
        )

        existing = self._session.execute(
            select(WatchlistSymbolTag).where(
                WatchlistSymbolTag.watchlist_id == watchlist_id,
                WatchlistSymbolTag.tag_id == tag_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        try:
            self._session.add(
                WatchlistSymbolTag(watchlist_id=watchlist_id, tag_id=tag_id)
            )
            self._session.flush()
        except IntegrityError:
            # Concurrent attach raced us between SELECT and INSERT — the
            # final state matches what the caller asked for, so swallow.
            self._session.rollback()

    def detach(self, *, user_id: int, watchlist_id: int, tag_id: int) -> None:
        """Idempotent detach. Missing attachment → no-op.

        Ownership is enforced so a user can't detach a tag from another
        user's watchlist row.
        """
        self._assert_ownership(
            user_id=user_id, watchlist_id=watchlist_id, tag_id=tag_id
        )
        self._session.execute(
            delete(WatchlistSymbolTag).where(
                WatchlistSymbolTag.watchlist_id == watchlist_id,
                WatchlistSymbolTag.tag_id == tag_id,
            )
        )
        self._session.flush()

    def list_attachments_for_watchlist(
        self, watchlist_id: int
    ) -> Sequence[WatchlistTag]:
        stmt = (
            select(WatchlistTag)
            .join(
                WatchlistSymbolTag,
                WatchlistSymbolTag.tag_id == WatchlistTag.id,
            )
            .where(WatchlistSymbolTag.watchlist_id == watchlist_id)
            .order_by(func.lower(WatchlistTag.name).asc())
        )
        return self._session.execute(stmt).scalars().all()

    def popular_for_user(
        self, user_id: int, limit: int = 8
    ) -> Sequence[WatchlistTag]:
        """Top-N tags by attachment count.

        Ties broken by ``name`` so the chip row is stable between
        renders. Tags with zero attachments still show — popularity is a
        ranking signal, not a filter, and EditTagsCard wants the full
        palette available as suggestions.
        """
        attach_count = func.count(WatchlistSymbolTag.watchlist_id).label("cnt")
        stmt = (
            select(WatchlistTag, attach_count)
            .outerjoin(
                WatchlistSymbolTag,
                WatchlistSymbolTag.tag_id == WatchlistTag.id,
            )
            .where(WatchlistTag.user_id == user_id)
            .group_by(WatchlistTag.id)
            .order_by(attach_count.desc(), func.lower(WatchlistTag.name).asc())
            .limit(limit)
        )
        return [row for row, _count in self._session.execute(stmt).all()]

    # ---------------- internal ---------------- #

    def _count_for_user(self, user_id: int) -> int:
        stmt = select(func.count(WatchlistTag.id)).where(
            WatchlistTag.user_id == user_id
        )
        return int(self._session.execute(stmt).scalar_one())

    def _find_by_name(self, *, user_id: int, name: str) -> WatchlistTag | None:
        stmt = select(WatchlistTag).where(
            WatchlistTag.user_id == user_id,
            func.lower(WatchlistTag.name) == name.lower(),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def _assert_ownership(
        self, *, user_id: int, watchlist_id: int, tag_id: int
    ) -> None:
        wl_owner = self._session.execute(
            select(Watchlist.user_id).where(Watchlist.id == watchlist_id)
        ).scalar_one_or_none()
        if wl_owner is None or wl_owner != user_id:
            raise NotFoundError(details={"watchlist_id": watchlist_id})

        tag_owner = self._session.execute(
            select(WatchlistTag.user_id).where(WatchlistTag.id == tag_id)
        ).scalar_one_or_none()
        if tag_owner is None or tag_owner != user_id:
            raise NotFoundError(details={"tag_id": tag_id})


def _normalize_name(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        from app.security.exceptions import ValidationError

        raise ValidationError(details={"reason": "empty_name"})
    if len(cleaned) > 32:
        from app.security.exceptions import ValidationError

        raise ValidationError(details={"reason": "name_too_long", "max": 32})
    return cleaned


def _validate_color(raw: str) -> str:
    cleaned = raw.strip()
    if not _HEX_COLOR_RE.match(cleaned):
        raise InvalidTagColorError(details={"color": cleaned})
    return cleaned

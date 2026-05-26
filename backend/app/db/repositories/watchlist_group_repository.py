"""Watchlist group CRUD — user-scoped.

Mirrors the ``WatchlistRepository`` patterns: every method takes
``user_id`` explicitly so multi-user separation is enforced at the
repository layer, not at the route layer.

Group deletion sets ``watchlist.group_id = NULL`` for any rows still
attached (the migration set ``ON DELETE SET NULL``). Repository drops
the membership explicitly before issuing ``session.delete`` so we get
predictable behaviour even when FK enforcement is off (some legacy
deployments). The CASCADE on the FK is the safety net; the explicit
UPDATE is the contract.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Watchlist, WatchlistGroup
from app.security.exceptions import EisweinError, NotFoundError

MAX_GROUPS_PER_USER = 20


class DuplicateGroupNameError(EisweinError):
    """409 — another group of the same name (case-insensitive) exists."""

    http_status = 409
    code = "group_duplicate_name"
    message = "群組名稱已存在"


class GroupLimitExceededError(EisweinError):
    """422 — user already has ``MAX_GROUPS_PER_USER`` groups."""

    http_status = 422
    code = "group_limit_exceeded"
    message = "群組數量已達上限"


class WatchlistGroupRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: int) -> Sequence[WatchlistGroup]:
        """Return groups sorted by ``(position ASC, id ASC)``.

        Stable secondary key on ``id`` because rapid reorder can leave
        two rows with the same position momentarily until the next
        :meth:`reorder` call cleans up.
        """
        stmt = (
            select(WatchlistGroup)
            .where(WatchlistGroup.user_id == user_id)
            .order_by(WatchlistGroup.position.asc(), WatchlistGroup.id.asc())
        )
        return self._session.execute(stmt).scalars().all()

    def get(self, *, user_id: int, group_id: int) -> WatchlistGroup | None:
        stmt = select(WatchlistGroup).where(
            WatchlistGroup.user_id == user_id,
            WatchlistGroup.id == group_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, *, user_id: int, name: str) -> WatchlistGroup:
        cleaned = _normalize_name(name)
        if self._count_for_user(user_id) >= MAX_GROUPS_PER_USER:
            raise GroupLimitExceededError(details={"max": MAX_GROUPS_PER_USER})
        if self._find_by_name(user_id=user_id, name=cleaned) is not None:
            raise DuplicateGroupNameError(details={"name": cleaned})
        next_position = self._next_position(user_id)
        row = WatchlistGroup(
            user_id=user_id,
            name=cleaned,
            position=next_position,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def rename(
        self,
        *,
        user_id: int,
        group_id: int,
        new_name: str,
    ) -> WatchlistGroup:
        cleaned = _normalize_name(new_name)
        row = self.get(user_id=user_id, group_id=group_id)
        if row is None:
            raise NotFoundError(details={"group_id": group_id})

        # Same name (case-insensitive) → no-op so the UI doesn't have to
        # special-case "renamed to the same string".
        if row.name.lower() != cleaned.lower():
            colliding = self._find_by_name(user_id=user_id, name=cleaned)
            if colliding is not None and colliding.id != row.id:
                raise DuplicateGroupNameError(details={"name": cleaned})

        row.name = cleaned
        self._session.flush()
        return row

    def reorder(self, *, user_id: int, ordered_group_ids: list[int]) -> None:
        """Set positions to 0..N-1 in the order listed.

        Raises :class:`NotFoundError` if ``ordered_group_ids`` does not
        match the user's current set exactly (different size or unknown
        id). This prevents partial reorders from silently dropping a
        group out of the sidebar.
        """
        current_rows = list(self.list_for_user(user_id))
        current_ids = {r.id for r in current_rows}
        requested_ids = set(ordered_group_ids)

        if len(ordered_group_ids) != len(current_rows) or requested_ids != current_ids:
            raise NotFoundError(
                details={
                    "reason": "id_set_mismatch",
                    "expected_ids": sorted(current_ids),
                    "received_ids": ordered_group_ids,
                }
            )

        by_id = {r.id: r for r in current_rows}
        for new_position, group_id in enumerate(ordered_group_ids):
            by_id[group_id].position = new_position
        self._session.flush()

    def delete(self, *, user_id: int, group_id: int) -> None:
        row = self.get(user_id=user_id, group_id=group_id)
        if row is None:
            raise NotFoundError(details={"group_id": group_id})

        # Explicit detach before deletion. The FK ON DELETE SET NULL
        # rule is the safety net for code paths that bypass the
        # repository (raw SQL, future migrations); the explicit UPDATE
        # is the documented contract.
        self._session.execute(
            update(Watchlist)
            .where(Watchlist.group_id == group_id)
            .values(group_id=None)
        )
        self._session.delete(row)
        self._session.flush()

    def count_symbols_per_group(self, user_id: int) -> dict[int, int]:
        """Return ``{group_id: symbol_count}`` for the user.

        Used by the ``GET /watchlist/groups`` route so the sidebar can
        render `(N)` next to each group name without a per-group COUNT.
        Rows with ``group_id=NULL`` (未分類) are intentionally excluded.
        """
        from sqlalchemy import func

        stmt = (
            select(Watchlist.group_id, func.count(Watchlist.id))
            .where(
                Watchlist.user_id == user_id,
                Watchlist.group_id.is_not(None),
            )
            .group_by(Watchlist.group_id)
        )
        return {int(gid): int(c) for gid, c in self._session.execute(stmt).all()}

    # ---------------- internal ---------------- #

    def _count_for_user(self, user_id: int) -> int:
        from sqlalchemy import func

        stmt = select(func.count(WatchlistGroup.id)).where(
            WatchlistGroup.user_id == user_id
        )
        result = self._session.execute(stmt).scalar_one()
        return int(result)

    def _next_position(self, user_id: int) -> int:
        from sqlalchemy import func

        stmt = select(func.max(WatchlistGroup.position)).where(
            WatchlistGroup.user_id == user_id
        )
        result = self._session.execute(stmt).scalar_one()
        return 0 if result is None else int(result) + 1

    def _find_by_name(self, *, user_id: int, name: str) -> WatchlistGroup | None:
        from sqlalchemy import func

        stmt = select(WatchlistGroup).where(
            WatchlistGroup.user_id == user_id,
            func.lower(WatchlistGroup.name) == name.lower(),
        )
        return self._session.execute(stmt).scalar_one_or_none()


def _normalize_name(raw: str) -> str:
    """Trim + length-clamp. ValidationError is the caller's job."""
    cleaned = raw.strip()
    if not cleaned:
        from app.security.exceptions import ValidationError

        raise ValidationError(details={"reason": "empty_name"})
    if len(cleaned) > 32:
        from app.security.exceptions import ValidationError

        raise ValidationError(details={"reason": "name_too_long", "max": 32})
    return cleaned

"""User queries and mutations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def by_id(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self._session.execute(stmt).scalar_one_or_none()

    def count(self) -> int:
        result = self._session.execute(select(User.id)).all()
        return len(result)

    def create(
        self,
        *,
        username: str,
        password_hash: str,
        email: str | None = None,
        is_admin: bool = False,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            is_admin=is_admin,
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        return user

    def record_successful_login(self, user: User, *, ip: str | None) -> None:
        user.last_login_at = datetime.now(timezone.utc)
        user.last_login_ip = ip
        user.failed_login_count = 0
        user.locked_until = None
        self._session.flush()

    def update_password(self, user: User, new_hash: str) -> None:
        user.password_hash = new_hash
        self._session.flush()

    def as_dict(self, user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "last_login_at": user.last_login_at,
        }

"""SQLAlchemy engine + session factory.

WAL mode is enabled via a connect event listener (NOT via `connect_args`
— sqlite3.connect() silently drops unknown kwargs, so `{"pragma": ...}`
would have no effect). This is a CLAUDE.md hard operational invariant.

Per-connection PRAGMAs
----------------------
* `journal_mode=WAL`         — concurrent reads while writer active
* `synchronous=NORMAL`       — WAL-recommended durability level
* `foreign_keys=ON`          — SQLite requires explicit enable per conn
* `busy_timeout=30000`       — wait up to 30s rather than immediate SQLITE_BUSY
* `auto_vacuum=INCREMENTAL`  — weekly vacuum job does incremental work (I15)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLAlchemy connect-event listener that enables WAL + safety PRAGMAs.

    Exposed at module level (not underscore-prefixed) because the test
    suite constructs its own engine and needs the exact same event
    listener to observe the same PRAGMA state.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
    finally:
        cursor.close()


def _ensure_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    rel = database_url.removeprefix("sqlite:///")
    if not rel or rel == ":memory:":
        return
    path = Path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings) -> Engine:
    _ensure_parent_dir(settings.database_url)
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
        future=True,
    )
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", apply_sqlite_pragmas)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Context-manager-like generator — for FastAPI Depends.

    Commits on clean exit, rolls back on exception, always closes.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

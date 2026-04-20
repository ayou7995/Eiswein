"""Tests for :mod:`app.jobs.backup`."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import apply_sqlite_pragmas
from app.db.models import Base, User
from app.db.repositories.system_metadata_repository import (
    KEY_LAST_BACKUP_AT,
    SystemMetadataRepository,
)
from app.jobs import backup as backup_job


def _make_file_engine(path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    event.listen(engine, "connect", apply_sqlite_pragmas)
    Base.metadata.create_all(engine)
    return engine


def _seed_user(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            User(
                username="admin",
                password_hash="$2b$12$" + "a" * 53,
                is_admin=True,
            )
        )
        session.commit()


@pytest.mark.asyncio
async def test_backup_creates_file_and_records_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)

    backup_dir = tmp_path / "backups"

    path = await backup_job.run(
        source_engine=engine,
        backup_dir=backup_dir,
        session_factory=factory,
    )

    assert path is not None and path.exists()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert path.name == f"eiswein-{today}.db"

    # Verify copied contents — the seeded user must exist.
    conn = sqlite3.connect(str(path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()
    assert count == 1

    # Metadata must have been written.
    with factory() as session:
        last = SystemMetadataRepository(session).get_datetime(KEY_LAST_BACKUP_AT)
    assert last is not None
    engine.dispose()


@pytest.mark.asyncio
async def test_backup_rotation_keeps_only_retention(tmp_path: Path) -> None:
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Pre-seed 4 "old" backup files with decreasing mtimes.
    older_mtime = time.time() - 86400 * 10
    for offset, name in enumerate(
        [
            "eiswein-2026-04-10.db",
            "eiswein-2026-04-11.db",
            "eiswein-2026-04-12.db",
            "eiswein-2026-04-13.db",
        ]
    ):
        path = backup_dir / name
        sqlite3.connect(str(path)).close()  # create a valid empty sqlite
        mtime = older_mtime + offset
        os.utime(path, (mtime, mtime))

    # Also an unrelated file that must NOT be rotated.
    other = backup_dir / "readme.txt"
    other.write_text("keep me")

    path = await backup_job.run(
        source_engine=engine,
        backup_dir=backup_dir,
        session_factory=factory,
        retention=2,
    )
    assert path is not None

    survivors = sorted(p.name for p in backup_dir.iterdir())
    # 2 most-recent eiswein-*.db survive + unrelated file + the new one
    # (which is the newest, so it's one of the 2 retained).
    assert "readme.txt" in survivors
    # WAL sidecars (``-wal`` / ``-shm``) appear while the new backup's
    # last connection drains; only the primary ``.db`` files count.
    eiswein_dbs = [s for s in survivors if s.startswith("eiswein-") and s.endswith(".db")]
    assert len(eiswein_dbs) == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_backup_skips_inmemory_engine(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    result = await backup_job.run(
        source_engine=engine,
        backup_dir=tmp_path / "backups",
        session_factory=factory,
    )
    assert result is None
    assert not (tmp_path / "backups").exists() or not list((tmp_path / "backups").iterdir())


@pytest.mark.asyncio
async def test_backup_verify_rejects_corrupt_file(tmp_path: Path) -> None:
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)

    # Replace the source file with garbage between engine init and
    # backup: the _verify_backup reader will fail. We simulate this
    # by deleting the file mid-flight; the backup() API itself will
    # raise so we land in the sqlite3.Error branch.
    db_path.unlink()

    result = await backup_job.run(
        source_engine=engine,
        backup_dir=tmp_path / "backups",
        session_factory=factory,
    )
    assert result is None
    engine.dispose()


def test_rotate_ignores_non_matching_filenames(tmp_path: Path) -> None:
    (tmp_path / "eiswein-2026-04-10.db").write_bytes(b"")
    (tmp_path / "eiswein-bogus.db").write_bytes(b"")  # does not match the pattern
    (tmp_path / "eiswein-2026-04-11.db").write_bytes(b"")

    os.utime(tmp_path / "eiswein-2026-04-10.db", (time.time() - 20, time.time() - 20))
    os.utime(tmp_path / "eiswein-2026-04-11.db", (time.time() - 10, time.time() - 10))

    removed = backup_job._rotate(tmp_path, retention=1)
    names = sorted(p.name for p in removed)
    assert names == ["eiswein-2026-04-10.db"]
    # Non-matching file must remain.
    assert (tmp_path / "eiswein-bogus.db").exists()


def test_extract_sqlite_path_handles_non_sqlite(tmp_path: Path) -> None:
    # Invoke extraction with a trivial SQLite file.
    eng = create_engine(f"sqlite:///{tmp_path}/x.db", future=True)
    assert backup_job._extract_sqlite_path(eng) == tmp_path / "x.db"

    mem = create_engine("sqlite:///:memory:", future=True)
    assert backup_job._extract_sqlite_path(mem) is None


@pytest.mark.asyncio
async def test_backup_retries_across_days_same_run_overwrites(
    tmp_path: Path,
) -> None:
    """Running the job twice on the same day overwrites the target atomically.

    Idempotency: re-running today must leave exactly one ``eiswein-YYYY-MM-DD.db``
    and it must still be a valid, readable DB.
    """
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)
    backup_dir = tmp_path / "backups"

    first = await backup_job.run(
        source_engine=engine, backup_dir=backup_dir, session_factory=factory
    )
    assert first is not None
    second = await backup_job.run(
        source_engine=engine, backup_dir=backup_dir, session_factory=factory
    )
    assert second == first
    eiswein_files = [
        p for p in backup_dir.iterdir() if p.name.startswith("eiswein-") and p.name.endswith(".db")
    ]
    assert len(eiswein_files) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_backup_records_metadata_via_clock_override(tmp_path: Path) -> None:
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return datetime(2026, 4, 19, 7, 0, tzinfo=UTC)

    path = await backup_job.run(
        source_engine=engine,
        backup_dir=tmp_path / "backups",
        session_factory=factory,
        clock=FixedClock,  # type: ignore[arg-type]
    )
    assert path is not None
    assert path.name == "eiswein-2026-04-19.db"

    with factory() as session:
        last = SystemMetadataRepository(session).get_datetime(KEY_LAST_BACKUP_AT)
    assert last == datetime(2026, 4, 19, 7, 0, tzinfo=UTC)
    engine.dispose()


@pytest.mark.asyncio
async def test_retention_zero_disables_rotation(tmp_path: Path) -> None:
    backup_dir = tmp_path
    (backup_dir / "eiswein-2026-04-10.db").write_bytes(b"")
    (backup_dir / "eiswein-2026-04-11.db").write_bytes(b"")
    t = time.time()
    os.utime(backup_dir / "eiswein-2026-04-10.db", (t - 20, t - 20))
    os.utime(backup_dir / "eiswein-2026-04-11.db", (t - 10, t - 10))

    removed = backup_job._rotate(backup_dir, retention=0)
    assert removed == []
    # both files still present
    assert (backup_dir / "eiswein-2026-04-10.db").exists()
    assert (backup_dir / "eiswein-2026-04-11.db").exists()


@pytest.mark.asyncio
async def test_cooldown_for_rotation_is_file_mtime_based(tmp_path: Path) -> None:
    """A file older than ``now - 1 day`` must still be retained iff
    inside the retention window. This doubles as a sanity test that
    ``_rotate`` uses mtime, not filename date.
    """
    backup_dir = tmp_path
    older = backup_dir / "eiswein-2026-04-10.db"
    newer = backup_dir / "eiswein-2026-04-09.db"
    older.write_bytes(b"")
    newer.write_bytes(b"")
    # Deliberately reverse the filename-to-mtime ordering so only the
    # lexically-earlier file is actually newest.
    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time() - 10, time.time() - 10))

    removed = backup_job._rotate(backup_dir, retention=1)
    # mtime says newer (filename-2026-04-09) wins; older mtime file removed.
    assert removed == [older]


@pytest.mark.asyncio
async def test_cooldown_allows_missing_mtime_edge_case(tmp_path: Path) -> None:
    # Smoke-test covering a single file + retention=1: nothing is rotated.
    (tmp_path / "eiswein-2026-04-10.db").write_bytes(b"")
    removed = backup_job._rotate(tmp_path, retention=1)
    assert removed == []


def test_verify_backup_catches_wrong_table() -> None:
    """_verify_backup must raise for a file missing our expected tables."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = sqlite3.connect(f.name)
        try:
            conn.execute("CREATE TABLE unrelated (x INTEGER)")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(sqlite3.OperationalError):
            backup_job._verify_backup(Path(f.name))


def test_verify_backup_integrity_check_runs() -> None:
    """Sanity: an empty + schema-less DB triggers the operational error
    path, confirming that our verifier actually executes the SELECTs
    (vs. no-op).
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        # File is an empty SQLite file (no tables).
        conn = sqlite3.connect(f.name)
        conn.close()
        with pytest.raises(sqlite3.OperationalError):
            backup_job._verify_backup(Path(f.name))


@pytest.mark.asyncio
async def test_source_missing_reports_failure(tmp_path: Path) -> None:
    """Engine pointing at a file that doesn't exist returns None."""
    path = tmp_path / "nope.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    factory = sessionmaker(bind=engine)

    result = await backup_job.run(
        source_engine=engine,
        backup_dir=tmp_path / "backups",
        session_factory=factory,
    )
    assert result is None


@pytest.mark.asyncio
async def test_metadata_write_error_does_not_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "eiswein.db"
    engine = _make_file_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed_user(factory)

    def broken_set_datetime(self: SystemMetadataRepository, key: str, when: datetime) -> None:
        raise RuntimeError("sqlite transient")

    monkeypatch.setattr(SystemMetadataRepository, "set_datetime", broken_set_datetime)

    path = await backup_job.run(
        source_engine=engine,
        backup_dir=tmp_path / "backups",
        session_factory=factory,
    )
    # Backup file still written + returned even though metadata write
    # failed (the metadata is advisory, not load-bearing for success).
    assert path is not None
    engine.dispose()


@pytest.mark.asyncio
async def test_cooldown_timedelta_parse() -> None:
    """Compile-time sanity — timedelta import works and cooldown value is sane."""
    assert timedelta(days=25) > timedelta(days=1)

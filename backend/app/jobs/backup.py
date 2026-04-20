"""Daily SQLite backup job (Phase 6, I1/I15).

Design
------
* Uses the SQLite ``Connection.backup()`` online-backup API — safe
  with WAL mode without pausing writes or flushing state.
* Destination filename: ``eiswein-YYYY-MM-DD.db`` in the configured
  backup directory so restoration is obvious without extra metadata.
* Verification step reopens the backup, runs a few sanity ``SELECT``s
  and counts rows in the core tables. Without verification, a
  silently-corrupted backup is worse than no backup.
* Retention: keep the 30 most-recent ``eiswein-*.db`` files (by
  mtime). Older files are unlinked. 30 days × ~2 MB/day is <100 MB
  for a single-user workload.
* On success, persists ``last_backup_at`` to ``system_metadata``.

All failures are logged + caught — a failed backup must not crash
the scheduler. The next scheduled run will retry fresh.
"""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories.system_metadata_repository import (
    KEY_LAST_BACKUP_AT,
    SystemMetadataRepository,
)

logger = structlog.get_logger("eiswein.jobs.backup")

JOB_NAME = "backup"

_BACKUP_RETENTION = 30
_BACKUP_NAME_RE = re.compile(r"^eiswein-\d{4}-\d{2}-\d{2}\.db$")

# Tables we expect to exist + have a predictable schema after phase 5.
# VACUUM / backup sanity check runs these as COUNT(*) so silent data
# loss (wrong file, truncated file) shows up immediately.
_VERIFY_TABLES: tuple[str, ...] = ("users", "watchlist", "daily_signal")


async def run(
    *,
    source_engine: Engine,
    backup_dir: Path,
    session_factory: sessionmaker[Session],
    retention: int = _BACKUP_RETENTION,
    clock: type[datetime] = datetime,
) -> Path | None:
    """Run one backup cycle.

    Returns the backup path on success, ``None`` on failure. Never
    raises — scheduler protocol.
    """
    logger.info("job_start", job_name=JOB_NAME)

    source_path = _extract_sqlite_path(source_engine)
    if source_path is None:
        logger.info(
            "job_skipped",
            job_name=JOB_NAME,
            reason="non_sqlite_or_memory",
        )
        return None
    if not source_path.exists():
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            reason="source_missing",
            source=str(source_path),
        )
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    now = clock.now(UTC)
    target = backup_dir / f"eiswein-{now.strftime('%Y-%m-%d')}.db"
    t0 = time.perf_counter()

    try:
        _atomic_backup(source=source_path, destination=target)
    except sqlite3.Error as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            reason="backup_api_error",
            error=str(exc),
        )
        _cleanup_partial(target)
        return None
    except OSError as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            reason="io_error",
            error=str(exc),
        )
        _cleanup_partial(target)
        return None

    try:
        _verify_backup(target)
    except (sqlite3.Error, AssertionError) as exc:
        logger.warning(
            "job_failed",
            job_name=JOB_NAME,
            reason="verification_failed",
            error=str(exc),
            target=str(target),
        )
        _cleanup_partial(target)
        return None

    duration_ms = int((time.perf_counter() - t0) * 1000)
    size_bytes = target.stat().st_size
    logger.info(
        "job_complete",
        job_name=JOB_NAME,
        backup_path=str(target),
        size_bytes=size_bytes,
        duration_ms=duration_ms,
    )

    rotated = _rotate(backup_dir, retention=retention)
    if rotated:
        logger.info(
            "backups_rotated",
            job_name=JOB_NAME,
            deleted=len(rotated),
            kept=retention,
        )

    _record_last_backup(session_factory=session_factory, when=now)
    return target


def _extract_sqlite_path(engine: Engine) -> Path | None:
    """Return the on-disk path for a SQLite engine, or ``None`` for
    in-memory / non-SQLite configurations.
    """
    if engine.url.get_backend_name() != "sqlite":
        return None
    db = engine.url.database
    if db is None or db == ":memory:" or not db:
        return None
    return Path(db)


def _atomic_backup(*, source: Path, destination: Path) -> None:
    """Copy ``source`` → ``destination`` via the SQLite backup API.

    Writes to a ``*.tmp`` file first and ``rename``s on success so a
    crash mid-copy never leaves a half-written ``eiswein-YYYY-MM-DD.db``
    that the verification step would then reject.
    """
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(str(tmp))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    tmp.replace(destination)
    # Backup contains bcrypt hashes + AES-GCM encrypted Schwab tokens.
    # chmod 0o600 so files inherit owner-only semantics regardless of
    # the process umask (security audit HIGH: backup-file-world-readable).
    destination.chmod(0o600)


def _verify_backup(path: Path) -> None:
    """Open the backup and run the sanity checks.

    Raises ``AssertionError`` on schema-level weirdness so the caller
    can classify the failure.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if row is None or row[0] != "ok":
            raise AssertionError(f"integrity_check={row[0] if row else None}")
        for table in _VERIFY_TABLES:
            # Parameter substitution isn't allowed for table names in
            # SQLite — each name comes from a hard-coded tuple (not
            # user input), so string interpolation is safe here.
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            count_row = cur.fetchone()
            if count_row is None:
                raise AssertionError(f"{table}: no count row")
            _ = int(count_row[0])
    finally:
        conn.close()


def _cleanup_partial(target: Path) -> None:
    """Remove a target file + its .tmp sibling after a failed backup."""
    for candidate in (target, target.with_suffix(target.suffix + ".tmp")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning(
                "cleanup_failed",
                job_name=JOB_NAME,
                path=str(candidate),
                error=str(exc),
            )


def _rotate(backup_dir: Path, *, retention: int) -> list[Path]:
    """Delete the oldest backups beyond ``retention``, return removed paths."""
    if retention <= 0:
        return []
    candidates = [p for p in backup_dir.iterdir() if _BACKUP_NAME_RE.match(p.name)]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    stale = candidates[retention:]
    deleted: list[Path] = []
    for p in stale:
        try:
            p.unlink()
            deleted.append(p)
        except OSError as exc:
            logger.warning(
                "rotate_failed",
                job_name=JOB_NAME,
                path=str(p),
                error=str(exc),
            )
    return deleted


def _record_last_backup(
    *,
    session_factory: sessionmaker[Session],
    when: datetime,
) -> None:
    try:
        with session_factory() as session:
            SystemMetadataRepository(session).set_datetime(KEY_LAST_BACKUP_AT, when)
            session.commit()
    except Exception as exc:
        logger.warning(
            "metadata_write_failed",
            job_name=JOB_NAME,
            key=KEY_LAST_BACKUP_AT,
            error_type=type(exc).__name__,
            error=str(exc),
        )

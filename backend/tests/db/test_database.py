"""Engine behavior: WAL PRAGMA is applied on connect."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import text

from app.config import Settings
from app.db.database import create_db_engine


def test_sqlite_wal_enabled(settings: Settings) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "wal_test.db"
        settings_with_file = settings.model_copy(update={"database_url": f"sqlite:///{db_path}"})
        engine = create_db_engine(settings_with_file)
        try:
            with engine.connect() as conn:
                mode = conn.execute(text("PRAGMA journal_mode")).scalar()
                fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
                busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
                sync = conn.execute(text("PRAGMA synchronous")).scalar()
            assert str(mode).lower() == "wal"
            assert int(fk or 0) == 1
            assert int(busy or 0) >= 30000
            # synchronous=NORMAL == 1
            assert int(sync or 0) == 1
        finally:
            engine.dispose()


def test_create_engine_creates_parent_dir(settings: Settings) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        nested = Path(tmp) / "nested" / "more" / "eis.db"
        assert not nested.parent.exists()
        patched = settings.model_copy(update={"database_url": f"sqlite:///{nested}"})
        engine = create_db_engine(patched)
        try:
            assert nested.parent.exists()
        finally:
            engine.dispose()
